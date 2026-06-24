import os
import uuid
import secrets
import threading
import tempfile
import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "meeting2024")
GCS_BUCKET = os.environ.get("GCS_BUCKET")  # set this in Cloud Run to enable GCS upload flow
UPLOAD_DIR = Path(tempfile.gettempdir()) / "meeting_web_jobs"
UPLOAD_DIR.mkdir(exist_ok=True)

jobs: dict[str, Any] = {}
_whisper_model = None
_model_lock = threading.Lock()

# Only import GCS libs when GCS_BUCKET is configured
_gauth = _gauth_requests = _gcs = None
if GCS_BUCKET:
    try:
        import google.auth as _gauth
        from google.auth.transport import requests as _gauth_requests
        from google.cloud import storage as _gcs
    except ImportError:
        print("WARNING: google-cloud-storage not installed; falling back to local upload mode")
        GCS_BUCKET = None

SYSTEM_PROMPT = """你是一位專業的會議記錄整理助理。
請根據提供的會議逐字稿，整理出一份結構清晰的中文會議紀錄。
逐字稿為中英混合，請統一以繁體中文輸出。"""

USER_PROMPT_TEMPLATE = """以下是會議逐字稿（含時間戳記）：

{transcript}

---

請根據以上逐字稿，產生一份會議紀錄，格式如下：

# 會議紀錄

## 基本資訊
- 日期：（從內容推斷，若無法判斷請填「請填寫」）
- 主題：（從內容摘要）
- 出席人員：（若能從對話辨識請列出，否則填「請填寫」）

## 討論重點
（條列式，每個主要議題一條，簡明描述）

## 決議事項
（條列式，若無明確決議請填「無」）

## 待辦行動項目（Action Items）
| 負責人 | 工作內容 | 預計完成日 |
|--------|----------|-----------|
（若無法從內容判斷負責人或日期，相應欄位填「待確認」）

## 備註
（其他需要注意的事項，若無則略去此節）
"""

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-05-20",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash-001",
    "gemini-2.0-flash-lite",
]


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        with _model_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel
                _whisper_model = WhisperModel("medium", device="cpu", compute_type="int8")
    return _whisper_model


def _process_job(job_id: str, video_path: Path, api_key: str):
    try:
        jobs[job_id]["status"] = "transcribing"
        jobs[job_id]["partial_transcript"] = ""
        model = _get_whisper_model()
        segments, _ = model.transcribe(
            str(video_path),
            language="zh",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        def _fmt(s: float) -> str:
            h, m, sec = int(s // 3600), int((s % 3600) // 60), int(s % 60)
            return f"{h:02d}:{m:02d}:{sec:02d}"

        lines = []
        for seg in segments:
            lines.append(f"[{_fmt(seg.start)}] {seg.text.strip()}")
            jobs[job_id]["partial_transcript"] = "\n".join(lines)
        transcript = "\n".join(lines)

        transcript_path = video_path.with_suffix(".txt")
        transcript_path.write_text(transcript, encoding="utf-8")
        jobs[job_id]["transcript_path"] = str(transcript_path)

        jobs[job_id]["status"] = "generating"
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=4096,
            temperature=0.2,
        )
        prompt = USER_PROMPT_TEMPLATE.format(transcript=transcript)

        minutes_text = None
        for model_name in GEMINI_MODELS:
            try:
                resp = client.models.generate_content(model=model_name, contents=prompt, config=config)
                minutes_text = resp.text
                break
            except Exception as e:
                if "NOT_FOUND" in str(e) or "not found" in str(e).lower():
                    continue
                raise

        if minutes_text is None:
            raise RuntimeError("所有 Gemini 模型均不可用，請確認 API Key 是否正確")

        minutes_path = video_path.with_suffix(".md")
        minutes_path.write_text(minutes_text, encoding="utf-8")
        jobs[job_id]["minutes_path"] = str(minutes_path)
        jobs[job_id]["status"] = "done"

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


def _require_auth(request: Request):
    token = request.cookies.get("auth_token", "")
    if not secrets.compare_digest(token.encode(), SITE_PASSWORD.encode()):
        raise HTTPException(status_code=401, detail="未授權，請先登入")


# ── Auth endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return {"gcs_mode": bool(GCS_BUCKET)}


@app.post("/api/login")
async def login(request: Request, response: Response):
    body = await request.json()
    pw = body.get("password", "")
    if not secrets.compare_digest(pw.encode(), SITE_PASSWORD.encode()):
        raise HTTPException(status_code=401, detail="密碼錯誤")
    is_https = request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        "auth_token", SITE_PASSWORD,
        httponly=True, samesite="strict",
        max_age=86400 * 7, secure=is_https,
    )
    return {"ok": True}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie("auth_token")
    return {"ok": True}


@app.get("/api/me")
async def me(request: Request):
    token = request.cookies.get("auth_token", "")
    return {"authenticated": secrets.compare_digest(token.encode(), SITE_PASSWORD.encode())}


# ── Local upload mode (no GCS_BUCKET, for local dev / testing) ────────────────

@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...), api_key: str = Form(...)):
    _require_auth(request)
    if not api_key.strip():
        raise HTTPException(status_code=400, detail="請提供 Gemini API Key")

    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir()

    filename = file.filename or "upload.mp4"
    video_path = job_dir / filename

    with open(video_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    jobs[job_id] = {"status": "queued", "filename": filename}
    threading.Thread(target=_process_job, args=(job_id, video_path, api_key), daemon=True).start()
    return {"job_id": job_id}


# ── GCS upload mode (Cloud Run production) ────────────────────────────────────

@app.post("/api/start-upload")
async def start_upload(request: Request, filename: str = Form(...), api_key: str = Form(...)):
    """Step 1: get a signed GCS URL so the browser can upload directly."""
    _require_auth(request)
    if not GCS_BUCKET:
        raise HTTPException(status_code=400, detail="伺服器未設定 GCS_BUCKET")
    if not api_key.strip():
        raise HTTPException(status_code=400, detail="請提供 Gemini API Key")

    job_id = str(uuid.uuid4())
    safe_name = Path(filename).name
    blob_name = f"uploads/{job_id}/{safe_name}"

    credentials, _ = _gauth.default()
    credentials.refresh(_gauth_requests.Request())

    client = _gcs.Client(credentials=credentials)
    blob = client.bucket(GCS_BUCKET).blob(blob_name)
    upload_url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=60),
        method="PUT",
        content_type="application/octet-stream",
        service_account_email=credentials.service_account_email,
        access_token=credentials.token,
    )

    jobs[job_id] = {
        "status": "uploading",
        "filename": safe_name,
        "blob_name": blob_name,
        "_api_key": api_key,
    }
    return {"job_id": job_id, "upload_url": upload_url}


@app.post("/api/process/{job_id}")
async def start_process(job_id: str, request: Request):
    """Step 2: called after browser finishes uploading to GCS."""
    _require_auth(request)
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到此工作")
    if not GCS_BUCKET:
        raise HTTPException(status_code=400, detail="伺服器未設定 GCS_BUCKET")

    job["status"] = "downloading"

    def download_and_process():
        try:
            job_dir = UPLOAD_DIR / job_id
            job_dir.mkdir(exist_ok=True)
            video_path = job_dir / job["filename"]

            from google.api_core import retry as _api_retry
            gcs_client = _gcs.Client()
            gcs_blob = gcs_client.bucket(GCS_BUCKET).blob(job["blob_name"])
            gcs_blob.download_to_filename(
                str(video_path),
                retry=_api_retry.Retry(deadline=600),
                timeout=600,
            )

            _process_job(job_id, video_path, job["_api_key"])

            # Clean up raw video from GCS after processing
            try:
                gcs_blob.delete()
            except Exception:
                pass
        except Exception as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = f"下載檔案失敗：{e}"

    threading.Thread(target=download_and_process, daemon=True).start()
    return {"ok": True}


# ── Status & download ──────────────────────────────────────────────────────────

@app.get("/api/status/{job_id}")
async def get_status(job_id: str, request: Request):
    _require_auth(request)
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到此工作")
    return {
        "status": job["status"],
        "error": job.get("error"),
        "has_transcript": "transcript_path" in job,
        "has_minutes": "minutes_path" in job,
        "partial_transcript": job.get("partial_transcript", ""),
    }


@app.get("/api/download/transcript/{job_id}")
async def download_transcript(job_id: str, request: Request):
    _require_auth(request)
    job = jobs.get(job_id)
    if not job or "transcript_path" not in job:
        raise HTTPException(status_code=404)
    p = Path(job["transcript_path"])
    stem = Path(job["filename"]).stem
    return FileResponse(str(p), filename=f"{stem}_逐字稿.txt", media_type="text/plain; charset=utf-8")


@app.get("/api/download/minutes/{job_id}")
async def download_minutes(job_id: str, request: Request):
    _require_auth(request)
    job = jobs.get(job_id)
    if not job or "minutes_path" not in job:
        raise HTTPException(status_code=404)
    p = Path(job["minutes_path"])
    stem = Path(job["filename"]).stem
    return FileResponse(str(p), filename=f"{stem}_會議紀錄.md", media_type="text/markdown; charset=utf-8")


# Serve frontend — must be last
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
