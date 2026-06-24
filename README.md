# 會議記錄自動化工具

自動將會議錄影（MP4）轉成逐字稿，再透過 AI 整理成結構化的繁體中文會議紀錄。

## 功能說明

```
MP4 錄影檔
   ↓  (faster-whisper，Whisper medium 模型)
逐字稿 .txt（含時間戳記）
   ↓  (Google Gemini API)
會議紀錄 .md（含議題摘要、決議、Action Items）
```

## 使用方式

本工具提供兩種使用模式：

---

### 模式一：本機 CLI（Windows PowerShell）

適合技術人員在自己電腦上執行。

#### 前置需求

1. Python 3.11+（已隨 `.venv` 虛擬環境配置）
2. 取得 Google Gemini API Key：前往 [Google AI Studio](https://aistudio.google.com/) 申請
3. 首次執行時，Whisper medium 模型會自動下載（約 1.5 GB，需等待）

#### 一鍵執行（建議方式）

```powershell
# 1. 設定 Gemini API Key（每個 PowerShell session 只需設定一次）
$env:GEMINI_API_KEY = "your-api-key-here"

# 2. 執行一鍵腳本
.\run.ps1 ".\你的會議錄影.mp4"
```

執行完成後，同一資料夾會產生：
- `你的會議錄影.txt` — 逐字稿（含時間戳記）
- `你的會議錄影.md` — 會議紀錄

#### 分步執行（手動）

```powershell
# 步驟 1：轉錄
.\.venv\Scripts\python.exe .\transcribe.py ".\會議.mp4"

# 步驟 2：產生會議紀錄（需先設定 GEMINI_API_KEY）
.\.venv\Scripts\python.exe .\generate_minutes.py ".\會議.txt"
```

---

### 模式二：Web 介面（共用服務）

部署於 GCP Cloud Run，讓非技術人員也能透過瀏覽器上傳錄影並取得會議紀錄。

#### 使用步驟

1. 開啟服務網址，輸入站台密碼登入（預設：`meeting2024`，Cloud Run 環境由管理員設定）
2. 輸入您自己的 **Gemini API Key**（每次上傳需填入，不會儲存在伺服器）
3. 選擇 MP4 錄影檔案並上傳
4. 等待進度完成（轉錄中 → 產生紀錄中 → 完成）
5. 下載逐字稿（`.txt`）或會議紀錄（`.md`）

---

## 檔案結構

```
meeting_record/
├── transcribe.py           # 轉錄腳本：MP4 → 逐字稿 .txt
├── generate_minutes.py     # 紀錄腳本：逐字稿 .txt → 會議紀錄 .md
├── run.ps1                 # PowerShell 一鍵腳本（執行以上兩步）
├── .venv/                  # Python 虛擬環境（包含所有相依套件）
└── web/                    # Web 介面服務
    ├── app.py              # FastAPI 後端
    ├── static/
    │   └── index.html      # 前端單頁應用（Tailwind CSS）
    ├── requirements.txt    # Python 相依套件
    ├── Dockerfile          # GCP Cloud Run 部署設定
    └── cors.json           # GCS Bucket CORS 設定
```

## 技術棧

| 元件 | 技術 |
|------|------|
| 語音轉文字 | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) medium 模型（CPU, int8） |
| 會議紀錄生成 | Google Gemini API（gemini-2.5-flash，自動 fallback 至舊版模型） |
| Web 後端 | FastAPI + Uvicorn |
| Web 前端 | 單頁 HTML + Tailwind CSS（CDN，無需 build） |
| 大檔上傳 | Google Cloud Storage（Cloud Run 環境）|
| 部署 | GCP Cloud Run |

## 輸出範例

**逐字稿（.txt）**
```
[00:00:05] 今天主要是要跟大家說明這次專案的時程規劃。
[00:00:12] 我們預計在六月底之前完成第一階段的評估。
```

**會議紀錄（.md）** 包含：
- 基本資訊（日期、主題、出席人員）
- 討論重點（條列式）
- 決議事項
- 待辦行動項目（Action Items，含負責人與預計完成日）

## Web 服務部署（管理員）

### 首次部署

```bash
# 進入 web/ 目錄
cd web

# 設定 GCS Bucket 的 CORS（只需執行一次）
gsutil cors set cors.json gs://your-bucket-name

# 部署至 Cloud Run（--source 會自動透過 Cloud Build 建置 Docker image）
gcloud run deploy meeting-web \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-env-vars SITE_PASSWORD=your-password,GCS_BUCKET=your-bucket-name
```

### 重新部署（更新程式碼）

環境變數不需重新設定，Cloud Run 會保留原本的值：

```bash
cd web

gcloud run deploy meeting-web --source . --region asia-east1
```

Build 需要約 5–10 分鐘（含 Whisper model 下載），完成後自動切換新版本，服務不中斷。

**環境變數說明：**

| 變數名稱 | 說明 | 預設值 |
|----------|------|--------|
| `SITE_PASSWORD` | 網站登入密碼 | `meeting2024` |
| `GCS_BUCKET` | GCS Bucket 名稱（啟用大檔上傳模式） | 未設定（使用本機暫存） |

## 注意事項

- Whisper medium 模型首次下載約 1.5 GB，建議在 Dockerfile 建置時預先下載（已設定）。
- Gemini API Key 由**使用者自行提供**，不會持久化儲存於伺服器，請自行至 [Google AI Studio](https://aistudio.google.com/) 申請。
- Cloud Run 為無狀態服務，重啟後進行中的工作紀錄會消失；已完成並下載的檔案不受影響。
- 逐字稿語言設定為中文（`language="zh"`），若需轉錄其他語言需修改 `transcribe.py` 或 `web/app.py`。
