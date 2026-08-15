# syntax=docker/dockerfile:1

# ---------- Stage 1: build the React frontend ----------------------------
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: Python runtime ---------------------------------------
FROM python:3.11-slim AS runtime

# System deps:
#  - tesseract-ocr: OCR fallback for scanned dashboard PDFs (dashboard_ingest.py)
#  - libgl1 / poppler-utils: PyMuPDF / image rendering
#  - fonts + Playwright's own installer for headless Chromium (force_render scans)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        poppler-utils \
        wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright's own Chromium + its OS-level deps (fonts, libnss3, etc.)
RUN playwright install --with-deps chromium

COPY . .
# Overwrite with the frontend built in stage 1 (dist/ isn't needed from the
# build context -- keeps the image from depending on node_modules at all).
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Writable data dirs (reports/uploads/corpus) -- see the docs/render.yaml
# notes about mounting a persistent volume at /app in production.
RUN mkdir -p reports uploads

ENV PYTHONUNBUFFERED=1 \
    WEBAPP_PORT=8005

EXPOSE 8005

CMD ["sh", "-c", "gunicorn -w 2 -k gthread --threads 4 -t 120 -b 0.0.0.0:${WEBAPP_PORT} webapp:app"]
