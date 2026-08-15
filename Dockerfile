# syntax=docker/dockerfile:1
# Backend-only image for the Vercel (frontend) + Render (this) split deploy.
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        poppler-utils \
        wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps chromium

COPY . .

RUN mkdir -p reports uploads

ENV PYTHONUNBUFFERED=1

# Render provides PORT at runtime (normally 10000). Keep 8005 as a local fallback.
EXPOSE 10000

CMD ["sh", "-c", "gunicorn -w 2 -k gthread --threads 4 -t 120 -b 0.0.0.0:${PORT:-8005} webapp:app"]
