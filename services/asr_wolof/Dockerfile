# Service de transcription du wolof (Kiriku) : voir serveur.py.
# torch CPU par défaut ; pour un GPU NVIDIA, remplacer l'index CPU par celui de CUDA.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=300 --retries 10 --index-url https://download.pytorch.org/whl/cpu torch==2.14.0 \
    && pip install --no-cache-dir --default-timeout=300 --retries 10 -r requirements.txt

RUN useradd --create-home --uid 1000 asr && mkdir -p /app/.cache/huggingface && chown -R asr:asr /app
COPY --chown=asr:asr serveur.py .
USER asr
ENV HF_HOME=/app/.cache/huggingface PYTHONUNBUFFERED=1

EXPOSE 8010
CMD ["python", "serveur.py"]
