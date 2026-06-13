FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5050

# Liveness probe used by orchestrators / docker-compose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://localhost:5050/api/health || exit 1

# Production WSGI server. LLM/embedding calls are IO/compute bound, so use a
# small number of threaded workers. Tune -w / --threads for your hardware.
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "4", \
     "-b", "0.0.0.0:5050", "--timeout", "120", "src.app:app"]
