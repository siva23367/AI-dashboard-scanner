"""
pdf_export.py -- turn a Sriya Web Intelligence HTML report into a PDF.

Design choice: this does NOT re-implement the report layout in a PDF library
(reportlab/weasyprint/fpdf). It prints the *same* HTML string that
`pro_scanner.html_report()` / `competitor_compare.html_comparison()` already
produce, using the headless Chromium that's already a project dependency
(`playwright`). That means:

  - The PDF is always pixel-faithful to the HTML report -- same score cards,
    same colors, same tables -- because it IS that HTML, printed.
  - There is exactly one place that defines what a report looks like
    (`html_report()`), so future report changes never need a second,
    PDF-specific update.

If Chromium/Playwright isn't available in the environment, this raises
`PDFExportUnavailable` with an actionable message. Callers should catch this
and continue -- a missing PDF must never fail an otherwise-successful scan.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


class PDFExportUnavailable(RuntimeError):
    """Chromium/Playwright isn't available to render a PDF."""


def html_to_pdf(html: str, out_path, *, landscape: bool = False) -> Path:
    """Render an HTML report string to a PDF file at out_path.

    Parameters
    ----------
    html: the full HTML document string (e.g. output of html_report(r)).
    out_path: destination .pdf path.
    landscape: use landscape orientation (useful for wide comparison tables).
    """
    out_path = Path(out_path)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise PDFExportUnavailable(
            "playwright is not installed. Run: pip install playwright"
        ) from e

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp_html = f.name

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as e:
                raise PDFExportUnavailable(
                    "Chromium isn't installed for Playwright. Run: playwright install chromium"
                ) from e
            try:
                page = browser.new_page()
                page.goto(f"file://{tmp_html}")
                page.wait_for_load_state("networkidle")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                page.pdf(
                    path=str(out_path),
                    format="A4",
                    print_background=True,
                    landscape=landscape,
                    margin={"top": "16mm", "bottom": "16mm", "left": "12mm", "right": "12mm"},
                )
            finally:
                browser.close()
    finally:
        Path(tmp_html).unlink(missing_ok=True)

    return out_path


def try_html_to_pdf(html: str, out_path, *, landscape: bool = False, label: str = "report"):
    """Best-effort wrapper for CLI use: prints a warning and returns None on
    failure instead of raising, so a PDF problem never kills the scan run."""
    try:
        path = html_to_pdf(html, out_path, landscape=landscape)
        print(f"[pro] PDF: {path}")
        return path
    except PDFExportUnavailable as e:
        print(f"[pro] Skipped PDF export for {label} ({e})")
        return None
