# Changelog — E-Commerce-only build

## Web UI (new)
- New `webapp.py`: login-gated Flask front end. Home page offers three
  options -- **Dashboard**, **PDF**, **Website Link** -- matching the
  founder's requested flow. Calls straight into the existing
  `scanner.py`/`pro_scanner.py`/`dashboard_ingest.py`/`pdf_export.py`
  functions, no duplicated logic.
  - **Website Link** -> full audit (semantic + spelling + SEO + accessibility
    + security + performance + conversion) -> JSON+HTML+PDF report.
  - **PDF** -> `dashboard_ingest.py` text/OCR pipeline -> corpus update ->
    dashboard summary report (pages, chunks, extraction methods, extracted
    metrics) -> also exported as JSON+HTML+PDF.
  - **Dashboard** -> lists every report from either flow, newest first.
  - Reports saved under `reports/<id>/`, indexed in `reports/index.json`;
    uploads saved under `uploads/`.
  - Single-user session login (`WEBAPP_USERNAME`/`WEBAPP_PASSWORD`/
    `WEBAPP_SECRET_KEY` env vars; defaults to `admin`/`admin` for local
    testing only -- documented in `PRO_README.md` not to ship that default).
  - `requirements.txt` gained `flask>=3.0`; new `run_webapp.sh` launcher
    (serves on port 8005 by default, matching the existing dashboard app's
    port convention).
  - Smoke-tested: login redirect gating, bad/good login, all three option
    pages, and a full PDF upload -> ingest -> report -> dashboard-listing
    round trip.

## DXI/SXI readiness scoring removed
- Removed the `dxi`/`sxi`/`dxi_sxi_readiness` score categories, the
  `telemetry_audit()` function, and the site-search/autocomplete ("SXI")
  checks inside `ecommerce_audit()` from `pro_scanner.py`.
- Removed the "DXI / SXI Readiness" section from the HTML/PDF report and
  the DXI/SXI console lines.
- `competitor_compare.py`'s score-comparison table and gap analysis no
  longer include `dxi`/`sxi`/`dxi_sxi_readiness` columns.
- Renamed the internal `dxi_signal` metadata field (used to tag *why* an
  issue matters, e.g. "trust", "urgency", "checkout confidence") to the
  neutral `signal_tag` in `pro_scanner.py` and `trust_signals.py`, since it
  was never DXI-specific — it's used across conversion/trust/SEO issues too.
  While touching this, fixed a bug in `trust_signals.py` where every
  opportunity's tag was being set to an undefined `dxi_signal` instead of
  its own value (all trust-signal issues were silently getting the same,
  incorrect tag before this fix).
- `categories` in `build_report()` is now
  `["accessibility","seo","performance","security","conversion"]`.
- Everything else (schema/SEO/security/performance/conversion audits,
  revenue impact, web vitals, competitor benchmarking, PDF export) is
  unchanged.

## PDF report export
- New `pdf_export.py`: renders the existing HTML report through headless
  Chromium (Playwright, already a dependency) into a `.pdf`, so the PDF is
  always pixel-identical to the `.html` report -- one report layout, three
  output formats.
- `pro_scanner.py` now writes `<out>.pdf` next to `<out>.json`/`<out>.html`
  on every run (scan report, and the `--competitors` benchmark). Skip with
  `--no-pdf`.
- `competitor_compare.py` standalone CLI gained the same `--no-pdf` flag and
  now writes a landscape `.pdf` of the comparison table by default.
- Failure mode: if Chromium isn't installed, PDF export prints a one-line
  warning and the run still completes with JSON+HTML -- a missing PDF never
  fails the scan.


Implements the Tier 1 (and part of Tier 2) items from the Feature Roadmap doc.
Only `scanner.py` changed — `rag.py` and `llm_judge.py` are unmodified and
included here just so the folder still runs as a complete set.

## 1. PDP-only scope (generic-site fallback removed)
- `extract_content()` no longer scrapes generic body text as a fallback.
- New `is_product_page(soup, content)` gate: a page must have highlight
  bullets, a detected price, or Product schema.org JSON-LD to be scanned.
  Anything else (category/listing pages, cart, blog, etc.) is **skipped**,
  not weakly scanned.
- `ScanReport` gained `skipped` / `skip_reason` fields; all four report
  writers (console, JSON, CSV via issues-only, HTML) reflect this.
- `SiteReport` gained `skipped_count` and a `scanned_pages()` helper so
  site-wide checks (below) only look at real PDPs.

## 2. SKU / model / brand whitelist learned across a catalog crawl
- `run_spelling_checks()` now accepts `catalog_brand_words`, a set that
  grows as `--crawl` visits more PDPs (seeded from each page's title via
  `_title_brand_tokens()`), on top of the existing per-page repeated-word
  detector. Reduces false positives on model numbers/brand names that only
  appear once on a given page but repeatedly across the catalog.

## 3. New per-page checks (in `run_semantic_checks`)
- `check_meta_tags()` — `<title>` length, meta description presence/length.
- `check_canonical_robots()` — missing canonical tag, unexpected `noindex`.
- `check_stock_status()` — flags an enabled Add to Cart/Buy Now control on a
  page whose text says the item is out of stock/sold out.
- `check_broken_cta_links()` — HEAD/GET-checks the Add to Cart/Buy Now and
  "related product" links (bounded to `MAX_LINKS_TO_CHECK = 12`) for 4xx/5xx.
- `check_price_format()` — flags price text with no currency symbol/code, or
  obviously malformed punctuation.

## 4. New catalog-wide checks (run once after a `--crawl` finishes)
- `check_duplicate_descriptions(site_report)` — TF-IDF + cosine similarity
  (same approach as `rag.py`) across every scanned PDP's description;
  flags pairs above `DUPLICATE_DESCRIPTION_THRESHOLD = 0.85`.
- `check_catalog_price_consistency(site_report)` — flags PDPs whose price
  currency symbol doesn't match the catalog's majority currency.

## Notes
- No new dependencies — `scikit-learn` (for TF-IDF) was already in
  `requirements.txt`.
- `check_broken_cta_links` makes real HTTP requests; pass `check_links=False`
  to `scan_url()` / disable per-page if you want a link-check-free run.
- All changes verified with a local synthetic-HTML test harness (no network
  dependency) — see the four checks: PDP detection, spelling+semantic
  issues, out-of-stock/CTA mismatch, and duplicate-description detection
  across two synthetic PDPs, all produced the expected output.
