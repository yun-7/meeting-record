FROM python:3.11-slim AS deps

WORKDIR /app

# ffmpeg is required by faster-whisper to decode audio from video files
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- CI pipeline builds up to here (--target=deps) ----

FROM deps AS final

# Pre-download Whisper medium model into the image so cold starts are fast
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8'); print('Whisper model cached.')"

COPY . .

# Cloud Run injects PORT; default to 8080
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port $PORT"]
