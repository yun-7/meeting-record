import sys
import os
from pathlib import Path
from faster_whisper import WhisperModel

def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def transcribe(video_path: str) -> str:
    video_path = Path(video_path)
    if not video_path.exists():
        print(f"錯誤：找不到檔案 {video_path}")
        sys.exit(1)

    output_path = video_path.with_suffix(".txt")

    print(f"載入 Whisper medium 模型（首次執行需下載，約 1.5GB）...")
    model = WhisperModel("medium", device="cpu", compute_type="int8")

    print(f"開始轉錄：{video_path.name}")
    segments, info = model.transcribe(
        str(video_path),
        language="zh",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    print(f"偵測語言：{info.language}（信心度 {info.language_probability:.0%}）")

    lines = []
    for segment in segments:
        timestamp = format_time(segment.start)
        text = segment.text.strip()
        line = f"[{timestamp}] {text}"
        lines.append(line)
        print(line)

    content = "\n".join(lines)
    output_path.write_text(content, encoding="utf-8")
    print(f"\n轉錄完成，已儲存至：{output_path}")
    return str(output_path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python transcribe.py <影片路徑>")
        print("範例：python transcribe.py meeting.mp4")
        sys.exit(1)
    transcribe(sys.argv[1])
