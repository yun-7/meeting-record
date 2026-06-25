"""Functional tests for the meeting-record FastAPI app.

Heavy dependencies (faster-whisper, google-genai, opencc, GCS) are all
imported inside functions in app.py, so these tests run without them.
Threading is patched so no background jobs actually execute.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# conftest.py sets SITE_PASSWORD and removes GCS_BUCKET before this import.
from app import app, jobs

PASS = "testpass"


@pytest.fixture(autouse=True)
def clear_jobs():
    jobs.clear()
    yield
    jobs.clear()


def authed(client: TestClient) -> TestClient:
    client.cookies.set("auth_token", PASS)
    return client


@pytest.fixture
def c():
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


@pytest.fixture
def ac(c):
    return authed(c)


# ── Config ─────────────────────────────────────────────────────────────────────

def test_config_gcs_mode_off(c):
    res = c.get("/api/config")
    assert res.status_code == 200
    assert res.json() == {"gcs_mode": False}


# ── Auth ───────────────────────────────────────────────────────────────────────

def test_me_unauthenticated(c):
    res = c.get("/api/me")
    assert res.status_code == 200
    assert res.json()["authenticated"] is False


def test_login_success(c):
    res = c.post("/api/login", json={"password": PASS})
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_login_wrong_password(c):
    res = c.post("/api/login", json={"password": "wrong"})
    assert res.status_code == 401


def test_me_authenticated(ac):
    res = ac.get("/api/me")
    assert res.status_code == 200
    assert res.json()["authenticated"] is True


def test_logout_clears_auth(c):
    # Login to get a real cookie in the session
    c.post("/api/login", json={"password": PASS})
    assert c.get("/api/me").json()["authenticated"] is True
    # Logout then verify subsequent requests are rejected
    res = c.post("/api/logout")
    assert res.status_code == 200
    assert c.get("/api/me").json()["authenticated"] is False


# ── Upload video/audio (Phase 1 — transcription) ───────────────────────────────

def test_upload_requires_auth(c):
    res = c.post("/api/upload", data={"api_key": "k"},
                 files={"file": ("x.mp4", b"data", "video/mp4")})
    assert res.status_code == 401


def test_upload_requires_api_key(ac):
    # Empty api_key: our handler returns 400; Pydantic V2 may return 422 — both are client errors.
    res = ac.post("/api/upload", data={"api_key": ""},
                  files={"file": ("x.mp4", b"data", "video/mp4")})
    assert res.status_code in (400, 422)


@patch("app.threading.Thread")
def test_upload_creates_job(mock_thread, ac):
    mock_thread.return_value = MagicMock()
    res = ac.post("/api/upload", data={"api_key": "mykey"},
                  files={"file": ("meeting.mp4", b"videodata", "video/mp4")})
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    assert job_id in jobs
    assert jobs[job_id]["filename"] == "meeting.mp4"
    assert jobs[job_id]["_api_key"] == "mykey"
    assert jobs[job_id]["status"] == "queued"
    mock_thread.return_value.start.assert_called_once()


# ── Upload text transcript (Phase 2 direct) ────────────────────────────────────

def test_upload_text_requires_auth(c):
    res = c.post("/api/upload-text", data={"api_key": "k"},
                 files={"file": ("t.txt", b"hello", "text/plain")})
    assert res.status_code == 401


def test_upload_text_requires_api_key(ac):
    res = ac.post("/api/upload-text", data={"api_key": ""},
                  files={"file": ("t.txt", b"hello", "text/plain")})
    assert res.status_code in (400, 422)


@patch("app.threading.Thread")
def test_upload_text_creates_job_and_starts_generation(mock_thread, ac):
    mock_thread.return_value = MagicMock()
    content = b"[00:00:01] \xe6\x9c\x83\xe8\xad\xb0\xe9\x96\x8b\xe5\xa7\x8b\n"  # UTF-8
    res = ac.post("/api/upload-text", data={"api_key": "mykey"},
                  files={"file": ("transcript.txt", content, "text/plain")})
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    assert job_id in jobs
    job = jobs[job_id]
    assert "transcript_path" in job
    assert Path(job["transcript_path"]).exists()
    assert job["_api_key"] == "mykey"
    # Phase 2 thread must be started immediately
    mock_thread.return_value.start.assert_called_once()


# ── Job status ──────────────────────────────────────────────────────────────────

def test_status_not_found(ac):
    res = ac.get("/api/status/no-such-id")
    assert res.status_code == 404


def test_status_transcribing(ac):
    jobs["j1"] = {"status": "transcribing", "filename": "a.mp4", "partial_transcript": "Hello"}
    res = ac.get("/api/status/j1")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "transcribing"
    assert data["partial_transcript"] == "Hello"
    assert data["has_transcript"] is False
    assert data["has_minutes"] is False


def test_status_done(ac):
    jobs["j2"] = {
        "status": "done",
        "filename": "b.mp4",
        "transcript_path": "/tmp/b.txt",
        "minutes_path": "/tmp/b.md",
    }
    res = ac.get("/api/status/j2")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "done"
    assert data["has_transcript"] is True
    assert data["has_minutes"] is True


def test_status_requires_auth(c):
    jobs["j3"] = {"status": "done", "filename": "c.mp4"}
    res = c.get("/api/status/j3")
    assert res.status_code == 401


# ── Generate minutes (Phase 2 trigger) ─────────────────────────────────────────

def test_generate_minutes_not_found(ac):
    res = ac.post("/api/generate-minutes/no-such-job")
    assert res.status_code == 404


def test_generate_minutes_no_transcript_path(ac):
    jobs["g1"] = {"status": "transcribed", "_api_key": "k"}  # missing transcript_path
    res = ac.post("/api/generate-minutes/g1")
    assert res.status_code == 400


def test_generate_minutes_wrong_status(ac):
    jobs["g2"] = {"status": "transcribing", "transcript_path": "/tmp/x.txt", "_api_key": "k"}
    res = ac.post("/api/generate-minutes/g2")
    assert res.status_code == 400


@patch("app.threading.Thread")
def test_generate_minutes_ok(mock_thread, ac):
    mock_thread.return_value = MagicMock()
    jobs["g3"] = {"status": "transcribed", "transcript_path": "/tmp/x.txt", "_api_key": "mykey"}
    res = ac.post("/api/generate-minutes/g3")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    mock_thread.return_value.start.assert_called_once()


def test_generate_minutes_requires_auth(c):
    jobs["g4"] = {"status": "transcribed", "transcript_path": "/tmp/x.txt", "_api_key": "k"}
    res = c.post("/api/generate-minutes/g4")
    assert res.status_code == 401


# ── Download ───────────────────────────────────────────────────────────────────

def test_download_transcript_job_not_found(ac):
    res = ac.get("/api/download/transcript/no-job")
    assert res.status_code == 404


def test_download_transcript_no_path_in_job(ac):
    jobs["d1"] = {"status": "transcribing", "filename": "a.mp4"}
    res = ac.get("/api/download/transcript/d1")
    assert res.status_code == 404


def test_download_transcript_serves_file(ac):
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                     mode="w", encoding="utf-8") as f:
        f.write("[00:00:01] 測試逐字稿內容\n")
        tmp = f.name
    try:
        jobs["d2"] = {"status": "done", "filename": "meet.mp4", "transcript_path": tmp}
        res = ac.get("/api/download/transcript/d2")
        assert res.status_code == 200
        assert "逐字稿" in res.text
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_download_minutes_job_not_found(ac):
    res = ac.get("/api/download/minutes/no-job")
    assert res.status_code == 404


def test_download_minutes_no_path_in_job(ac):
    jobs["d3"] = {"status": "done", "filename": "a.mp4", "transcript_path": "/tmp/a.txt"}
    res = ac.get("/api/download/minutes/d3")
    assert res.status_code == 404


def test_download_minutes_serves_file(ac):
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False,
                                     mode="w", encoding="utf-8") as f:
        f.write("# 會議紀錄\n\n## 討論重點\n- 項目一\n")
        tmp = f.name
    try:
        jobs["d4"] = {"status": "done", "filename": "meet.mp4", "minutes_path": tmp}
        res = ac.get("/api/download/minutes/d4")
        assert res.status_code == 200
        assert "會議紀錄" in res.text
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_download_requires_auth(c):
    res = c.get("/api/download/transcript/any-id")
    assert res.status_code == 401


# ── Preview minutes ────────────────────────────────────────────────────────────

def test_preview_minutes_not_found(ac):
    res = ac.get("/api/preview/minutes/no-job")
    assert res.status_code == 404


def test_preview_minutes_no_path(ac):
    jobs["p1"] = {"status": "done", "filename": "a.mp4"}
    res = ac.get("/api/preview/minutes/p1")
    assert res.status_code == 404


def test_preview_minutes_returns_text(ac):
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False,
                                     mode="w", encoding="utf-8") as f:
        f.write("# 會議紀錄\n\n## 討論重點\n- 項目一\n")
        tmp = f.name
    try:
        jobs["p2"] = {"status": "done", "filename": "meet.mp4", "minutes_path": tmp}
        res = ac.get("/api/preview/minutes/p2")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/plain")
        assert "# 會議紀錄" in res.text
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_preview_minutes_requires_auth(c):
    res = c.get("/api/preview/minutes/any-id")
    assert res.status_code == 401
