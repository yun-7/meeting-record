# CI/CD 流程說明

本專案使用 **GCP Cloud Build** 搭配 **GitHub** 實現自動化測試與部署。

---

## 架構概覽

```
開 Pull Request
      │
      ▼
CI 自動檢查 (cloudbuild.ci.yaml)
  - Python 語法檢查
  - Docker 建置驗證
      │
      ▼ 通過後手動 Merge 到 main
      │
      ▼
CD 自動部署 (cloudbuild.cd.yaml)
  - 建置完整 Docker image
  - 推送到 Container Registry
  - 部署到 GCP Cloud Run
```

---

## Trigger 說明

| Trigger 名稱 | 觸發時機 | 執行內容 |
|---|---|---|
| `meeting-web-ci-pr` | 開 PR / 更新 PR | 語法檢查 + Docker 驗證 |
| `meeting-web-cd-deploy` | Merge 進 main | 完整建置並部署到 Cloud Run |

---

## CI 檢查內容（Pull Request）

**1. Python 語法檢查**
掃描所有 `.py` 檔，確保沒有語法錯誤。

**2. Docker 建置驗證**
只建置 Dockerfile 的 `deps` 階段（安裝 ffmpeg + pip 套件），跳過 Whisper 模型下載，約 3-5 分鐘完成。

> CI 不包含功能測試，若需新增請在 `web/cloudbuild.ci.yaml` 加入 pytest step。

---

## CD 部署流程（Push 到 main）

1. 拉取上一次的 image 作為快取來源
2. 建置完整 Docker image（含 Whisper 模型，首次約 10-15 分鐘，有快取後約 2-3 分鐘）
3. 推送兩個 tag：`:latest` 和 `:<commit-sha>`
4. 部署到 Cloud Run，環境變數從 Secret Manager 自動注入

---

## 環境變數與 Secrets

部署時所需的敏感設定存放於 **GCP Secret Manager**，不寫在程式碼中：

| Secret 名稱 | 對應環境變數 | 說明 |
|---|---|---|
| `meeting-web-site-password` | `SITE_PASSWORD` | 網站登入密碼 |
| `meeting-web-gcs-bucket` | `GCS_BUCKET` | GCS bucket 名稱 |

更新 secret 值：
```bash
echo -n "新密碼" | gcloud secrets versions add meeting-web-site-password --data-file=-
```

---

## 日常開發流程

```bash
# 1. 建立新 branch
git checkout -b feature/your-feature-name

# 2. 修改程式碼後 commit
git add .
git commit -m "feat: 說明你的變更"
git push -u origin feature/your-feature-name

# 3. 到 GitHub 開 Pull Request
#    → CI 自動跑（約 3-5 分鐘）
#    → CI 通過後 Merge 進 main
#    → CD 自動部署到 Cloud Run（約 2-15 分鐘）
```

---

## 建置速度參考

| 情境 | 預估時間 |
|---|---|
| CI（PR 檢查） | 3-5 分鐘 |
| CD 首次部署（無快取） | 10-15 分鐘 |
| CD 一般部署（有快取） | 2-3 分鐘 |

---

## 相關設定檔

| 檔案 | 說明 |
|---|---|
| `web/cloudbuild.ci.yaml` | CI pipeline 設定 |
| `web/cloudbuild.cd.yaml` | CD pipeline 設定 |
| `web/Dockerfile` | 多階段建置（`deps` + `final`） |

---

## Cloud Build 記錄查詢

GCP Console → Cloud Build → 記錄：
`https://console.cloud.google.com/cloud-build/builds?project=julia-500214`
