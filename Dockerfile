# The browser handles the microphone and the speakers, so nothing here needs audio
# devices. This image only ever sees numpy arrays and WAV bytes.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    HF_HOME=/cache/huggingface \
    KOKORO_MODEL=/models/kokoro-v1.0.onnx \
    KOKORO_VOICES=/models/voices-v1.0.bin \
    REPORT_FONT=/models/Inter.ttf

WORKDIR /app

# Dependencies first, against a stub package, so editing source does not reinstall
# everything. The real source lands in the next layer and replaces the stub.
COPY pyproject.toml README.md ./
RUN mkdir -p src/coach/modes \
    && touch src/coach/__init__.py src/coach/modes/__init__.py \
    && uv pip install --system --no-cache -e .

COPY main.py ./
COPY src/ ./src/
COPY web/ ./web/

# Whisper and Kokoro are big; keep them on volumes rather than in the image.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data /cache /models \
    && chown -R app:app /app /data /cache
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/modes', timeout=4)"

# 0.0.0.0 inside the container; compose only publishes it to 127.0.0.1 on the host.
CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8000", "--no-open"]
