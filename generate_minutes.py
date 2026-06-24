import sys
import os
from pathlib import Path
from google import genai
from google.genai import types

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

# 按優先順序嘗試，直到成功為止
CANDIDATE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-05-20",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash-001",
    "gemini-2.0-flash-lite",
]

def find_working_model(client: genai.Client, prompt: str, config) -> tuple[str, str]:
    for model in CANDIDATE_MODELS:
        try:
            print(f"  嘗試模型：{model}")
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            print(f"  使用模型：{model}")
            return model, response.text
        except Exception as e:
            err = str(e)
            if "NOT_FOUND" in err or "not found" in err.lower():
                continue
            raise
    raise RuntimeError(f"所有候選模型均不可用：{CANDIDATE_MODELS}")

def generate_minutes(txt_path: str) -> str:
    txt_path = Path(txt_path)
    if not txt_path.exists():
        print(f"錯誤：找不到逐字稿檔案 {txt_path}")
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("錯誤：請設定環境變數 GEMINI_API_KEY")
        print("設定方式：$env:GEMINI_API_KEY = 'your-api-key'")
        sys.exit(1)

    transcript = txt_path.read_text(encoding="utf-8")
    output_path = txt_path.with_suffix(".md")

    print(f"讀取逐字稿：{txt_path.name}（共 {len(transcript)} 字元）")
    print("呼叫 Gemini API 產生會議紀錄...")

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        max_output_tokens=4096,
        temperature=0.2,
    )

    _, minutes = find_working_model(client, USER_PROMPT_TEMPLATE.format(transcript=transcript), config)
    output_path.write_text(minutes, encoding="utf-8")
    print(f"會議紀錄已儲存至：{output_path}")
    return str(output_path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python generate_minutes.py <逐字稿路徑>")
        print("範例：python generate_minutes.py meeting.txt")
        sys.exit(1)
    generate_minutes(sys.argv[1])
