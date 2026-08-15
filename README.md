# Sriya Web Intelligence Scanner — Pro

## Why this version is stronger

The original scanner is a solid rule-based PDP auditor. Pro turns it into a founder-facing **Web Intelligence** product rather than a list of HTML warnings.

### New modules
- **Accessibility:** WCAG 2.2-oriented checks including labels, language, image alt text, heading hierarchy and target-size heuristics.
- **SEO:** title/description, canonical, viewport, robots/noindex, Open Graph, hreflang and Product/Offer structured-data completeness.
- **Security:** HTTPS plus HSTS, CSP, X-Content-Type-Options, Referrer-Policy, Permissions-Policy and clickjacking posture.
- **Performance:** lazy loading, modern image formats, image dimensions, script count, render-blocking script heuristics and preconnect.
- **Conversion:** CTA, price, reviews, delivery, returns and payment reassurance signals.
- **Executive scoring:** category scores + overall health.
- **Prioritization:** impact, confidence, remediation and quick-win roadmap.
- **Baseline:** compare the current report with a previous Pro JSON report.
- **HTML executive report:** designed for a founder/demo rather than raw developer logs.
- **PDF executive report:** every run also writes a `.pdf` next to the `.json`/`.html`
  (pass `--no-pdf` to skip it) — see `pdf_export.py`. It's a headless-Chromium print of
  the exact same HTML report, so it's always identical to what you see in the browser
  and there's nothing extra to keep in sync when the report layout changes.



Why: this scanner's proxy and the real DXI/SXI shown in the dashboard PDF (Marketing/
Demographic/Engagement/KPI/Transaction sub-scores computed from a CSV of user-level
data via a trained model) are different products that happened to share a name — one
reads a page's HTML, the other reads a dataset of numeric user/session records — and
that overlap was causing confusion about what the scanner actually measures. If DXI/SXI
scoring needs to come back later, it should be its own clearly-separate module, not
folded into this scanner's category list.


## Run

```bash
source .venv/bin/activate
python pro_scanner.py "https://example.com/product/abc"
```

Force browser rendering:

```bash
python pro_scanner.py "https://example.com/product/abc" --render
```

Generate a named report:

```bash
python pro_scanner.py "https://example.com/product/abc" --out amazon_pro
```

This writes `amazon_pro.json`, `amazon_pro.html`, and `amazon_pro.pdf`.
Skip the PDF (faster, no browser launch) with `--no-pdf`:

```bash
python pro_scanner.py "https://example.com/product/abc" --out amazon_pro --no-pdf
```

Compare with a previous scan:

```bash
python pro_scanner.py "https://example.com/product/abc" --baseline previous.json --out current
```

## LLM/RAG

The Pro scanner keeps the existing rule engine and RAG layer. LLM calls should enrich/group findings, not invent detections. If the LLM is unavailable, the deterministic checks still produce a valid report.

## Important product positioning

Do **not** tell a founder that a static HTML scan proves conversion lift, live user friction, or a security vulnerability. The scanner measures **readiness and detectable implementation signals**.

## Web UI (new)

`webapp.py` is a small login-gated Flask front end that wraps the CLI tools
above -- it does not re-implement any scoring/extraction logic, it only calls
`pro_scanner.py` / `scanner.py` / `dashboard_ingest.py` / `pdf_export.py`, so
the web UI and CLI always produce identical output.

```bash
source .venv/bin/activate
pip install -r requirements.txt   # picks up flask
./run_webapp.sh                   # serves on http://localhost:8005
```

Set real credentials before exposing this beyond localhost (defaults to
`admin`/`admin` otherwise):

```bash
export WEBAPP_USERNAME="youruser"
export WEBAPP_PASSWORD="yourpassword"
export WEBAPP_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
```

Flow: log in -> home page offers **Dashboard**, **PDF**, or **Website Link**.
- **Website Link** -- enter a PDP URL, runs the full audit (semantic issues +
  spelling from `scanner.py`, SEO/accessibility/security/performance/
  conversion from `pro_scanner.py`) and saves a JSON+HTML+PDF report.
- **PDF** -- upload a dashboard PDF/image, runs it through `dashboard_ingest.py`
  (text layer + OCR), adds it to the searchable corpus, and saves a dashboard
  summary report (pages, chunks, extracted metrics, extraction methods).
- **Dashboard** -- lists every report generated from either flow, newest
  first, with links to its HTML/PDF/JSON.

Reports are written under `reports/<id>/` and indexed in `reports/index.json`;
uploaded files land in `uploads/`. Both directories are created automatically.
