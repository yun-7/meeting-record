# CLAUDE.md — meeting-record

## 專案概述

自動將會議錄影／音訊轉成繁體中文逐字稿，再透過 Gemini API 整理成結構化會議紀錄。

**處理流程：**
```
上傳影片/音訊
  → ffmpeg 轉成 16kHz mono WAV（縮小檔案）
  → faster-whisper（Whisper medium, CPU, int8）→ 逐字稿 .txt
  → opencc 簡轉繁
  → Google Gemini API → 會議紀錄 .md
```

---

## 先讀這些檔案

| 檔案 | 說明 |
|------|------|
| `web/app.py` | FastAPI 後端，所有業務邏輯在這裡 |
| `web/static/index.html` | 前端單頁應用（純 HTML + Tailwind CDN） |
| `web/requirements.txt` | Python 相依套件 |
| `web/Dockerfile` | 多階段建置（`deps` → `final`，final 預下載 Whisper 模型） |
| `web/cloudbuild.cd.yaml` | CD pipeline，含 Cloud Run 部署設定 |
| `web/cloudbuild.ci.yaml` | CI pipeline（PR 觸發） |
| `CICD.md` | CI/CD 流程與標準開發流程說明 |
| `README.md` | 使用者說明文件 |

---

## GCP 基本資訊

| 項目 | 值 |
|------|---|
| Project ID | `julia-500214` |
| Cloud Run 服務名稱 | `meeting-web` |
| 部署區域 | `asia-east1` |
| Container Registry | `gcr.io/julia-500214/meeting-web` |

**Secret Manager（敏感設定不寫在程式碼）：**
| Secret 名稱 | 對應環境變數 | 說明 |
|---|---|---|
| `meeting-web-site-password` | `SITE_PASSWORD` | 網站登入密碼（預設 `meeting2024`） |
| `meeting-web-gcs-bucket` | `GCS_BUCKET` | GCS bucket 名稱 |

---

## Cloud Run 目前設定

```
--memory=4Gi
--cpu=2
--no-cpu-throttling        # 背景執行緒轉錄時 CPU 不被凍結
--min-instances=1          # 避免 scale-to-zero 殺掉進行中的 job
--max-instances=1          # job 存在記憶體，多 instance 會造成 404
--session-affinity         # 同一 client 固定打同一 instance
--execution-environment=gen2  # /tmp 32GB NVMe（gen1 只有 512MB，大檔會爆）
```

這些設定都在 `web/cloudbuild.cd.yaml` 的 deploy step 裡。

---

## 重要架構限制

**Jobs 存在記憶體（`jobs: dict`）**
- 容器重啟後所有 job 消失，status 查詢會回 404
- 這是目前架構的根本限制，因此才設 `--max-instances=1`
- 若未來需要多人同時使用，需改成 Firestore 或 Redis 持久化

**大檔案處理**
- 上傳走 GCS signed URL（瀏覽器直傳 GCS，不過 Cloud Run）
- Cloud Run 再從 GCS 下載到 `/tmp`，用 ffmpeg 轉 WAV 後才給 Whisper
- 原始影片下載後立即轉換並刪除，節省 `/tmp` 空間

---

## 開發工作流程

Web 功能**沒有本機測試環境**，所有測試都部署到 Cloud Run。

```bash
# 標準流程（不要直接 push main）
git checkout main && git pull origin main
git checkout -b fix/your-feature
# ... 修改 ...
git add <檔案>
git commit -m "fix: 說明"
git push -u origin fix/your-feature
# GitHub 開 PR → CI 自動跑 → merge → CD 自動部署
```

**CI/CD 觸發條件：**
- CI（語法檢查 + Docker 建置）：開 PR 或更新 PR
- CD（完整建置 + 部署）：merge 進 main

**不要直接 push main**，push 到其他 branch 不會觸發任何 pipeline。

---

## 查看 Cloud Run Logs

```bash
# 應用程式 stdout（含 [job:xxxxxxxx] 進度 log）
gcloud logging read \
  'logName="projects/julia-500214/logs/run.googleapis.com%2Fstdout"' \
  --limit=50 --format="table(timestamp,textPayload)" \
  --project=julia-500214 --order=desc

# 容器 crash / stderr
gcloud logging read \
  'logName="projects/julia-500214/logs/run.googleapis.com%2Fstderr"' \
  --limit=50 --format="table(timestamp,severity,textPayload)" \
  --project=julia-500214 --order=desc
```

Job log 格式：`[job:xxxxxxxx] started — file=xxx.mp4 size=850MB`

---

## 已知問題與注意事項

- **Gemini API 免費配額**：測試多次可能遇到 429，隔天重置
- **503 UNAVAILABLE**：Gemini 模型暫時高負載，app 會自動 fallback 到下一個 model
- **Whisper 輸出繁體字**：已用 `opencc s2t` 轉換，若出現簡體字代表 opencc 有問題
- **容器被殺 → 404**：部署期間進行中的 job 一定會消失，測試前確認 CD pipeline 已完成
- **Gemini 可用 model 清單**：`gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-2.5-flash-lite`, `gemini-2.0-flash-lite`, `gemini-flash-latest`（定義在 `app.py` 的 `GEMINI_MODELS`）
