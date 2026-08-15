# syntax=docker/dockerfile:1
#
# Backend-only image for the Vercel (frontend) + Render (this) split deploy.
# If you'd rather run everything from one Docker image/host instead (no
# Vercel), see README-DEPLOY.md's "single-image" section for the couple of
# lines that add back a `npm run build` stage and COPY the frontend/dist
# folder in -- webapp.py's /app route already knows how to serve it.
FROM python:3.11-slim AS runtime

# System deps:
#  - tesseract-ocr: OCR fallback for scanned dashboard PDFs (dashboard_ingest.py)
#  - libgl1 / poppler-utils: PyMuPDF / image rendering
#  - wget/gnupg/ca-certificates: needed by `playwright install --with-deps`
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

# Writable data dirs (reports/uploads/corpus) -- see the render.yaml /
# README-DEPLOY.md notes about mounting a persistent volume at DATA_DIR.
RUN mkdir -p reports uploads

ENV PYTHONUNBUFFERED=1 \
    WEBAPP_PORT=8005

EXPOSE 8005

CMD ["sh", "-c", "gunicorn -w 2 -k gthread --threads 4 -t 120 -b 0.0.0.0:${WEBAPP_PORT} webapp:app"]

