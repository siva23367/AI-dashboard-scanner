"""
Dashboard ingestion module
---------------------------
Turns image-based PDF/PNG/JPG dashboards (screenshots of BI tools, executive
summaries, KPI panels, etc.) into a persistent, structured, searchable
corpus. This is the "OCR / visual extraction" step in:

    Dashboard PDFs/images
      -> OCR / visual extraction              <-- this file
      -> Extract tables + chart labels + text + numbers   <-- this file
      -> Create searchable chunks             <-- this file (writes chunks)
      -> Semantic/vector search                <-- dashboard_search.py
      -> Product/entity matching               <-- dashboard_search.py
      -> Retrieve surrounding data              <-- dashboard_search.py
      -> LLM summarizes the findings            <-- dashboard_search.py

Design notes
------------
Most "dashboards" of this kind (Grafana/Metabase/custom-React screenshots,
PDF exports of a browser tab, etc.) have NO text layer at all -- they are
just a picture of a page. `fitz` (PyMuPDF) is used first to check for a
real text layer (cheap, exact); if the page has little/no extractable
text, we rasterize the page and OCR it with Tesseract via `pytesseract`.
Either way we keep the (x, y, width, height) bounding box of every text
line, because that's what lets us later group "a number" with "the label
above/beside it" -- e.g. associating "23.91%" with "Current Unique Buyer %"
purely from layout proximity, since OCR text order alone doesn't preserve
that relationship reliably on a card-grid dashboard.

Same "never break the core report" philosophy as the rest of this project:
if OCR/pdf parsing fails for one page or one file, we record what we could
and move on rather than crashing the whole ingest run.

Storage
-------
Everything is appended to a single JSON corpus file (default
`dashboard_corpus.json`) so `dashboard_search.py` can load it without
re-running OCR every time. Re-ingesting the same source file replaces its
previous entries (keyed by absolute file path), so you can re-run ingest
after updating a dashboard export.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None

DEFAULT_CORPUS_PATH = os.environ.get("DASHBOARD_CORPUS_PATH", "dashboard_corpus.json")

# Numbers, percentages, currency amounts -- pulled out separately from plain
# text so downstream retrieval/matching can treat "23.91%" as a metric value
# rather than just another word.
METRIC_RE = re.compile(
    r"(?:₹|rs\.?|\$|€|£)\s?[\d][\d,]*(?:\.\d+)?|"   # currency amounts
    r"\b\d[\d,]*\.\d+%?\b|"                          # decimals / decimal %
    r"\b\d[\d,]{2,}\b|"                              # thousands-separated ints
    r"\b\d+%\b",                                     # plain integer %
    re.I,
)


@dataclass
class Chunk:
    """One piece of extracted, positioned text from a dashboard page."""
    source_file: str          # absolute path of the PDF/image ingested
    dashboard_name: str       # human label, e.g. filename without extension
    page: int                 # 1-indexed page number (images are always 1)
    text: str                 # the raw line/block of text
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1) in page units
    extraction_method: str    # "pdf_text_layer" or "ocr"
    metrics_found: List[str] = field(default_factory=list)


@dataclass
class IngestResult:
    source_file: str
    dashboard_name: str
    pages: int
    chunks_added: int
    extraction_method_summary: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def _dashboard_name_from_path(path: str) -> str:
    base = os.path.basename(path)
    name, _ = os.path.splitext(base)
    return name


def _extract_metrics(text: str) -> List[str]:
    return [m.group(0).strip() for m in METRIC_RE.finditer(text)]


def _group_pdf_text_lines(page) -> List[Dict[str, Any]]:
    """Pull line-level text + bbox out of a PyMuPDF page that has a real
    text layer (rare for screenshot-style dashboards, common for
    programmatically-generated PDF exports)."""
    lines = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            x0 = min(s["bbox"][0] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            lines.append({"text": text, "bbox": (x0, y0, x1, y1)})
    return lines


def _ocr_page_image(pil_image, page_number: int) -> List[Dict[str, Any]]:
    """OCR a rasterized page/image and return line-grouped text + bbox,
    using Tesseract's word-level output grouped back into lines by
    (block_num, par_num, line_num)."""
    if pytesseract is None:
        return []
    data = pytesseract.image_to_data(pil_image, output_type=pytesseract.Output.DICT)
    lines: Dict[Tuple[int, int, int], Dict[str, Any]] = {}
    n = len(data.get("text", []))
    for i in range(n):
        word = data["text"][i].strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x, y, w, h = (data["left"][i], data["top"][i], data["width"][i], data["height"][i])
        if key not in lines:
            lines[key] = {"words": [word], "x0": x, "y0": y, "x1": x + w, "y1": y + h}
        else:
            entry = lines[key]
            entry["words"].append(word)
            entry["x0"] = min(entry["x0"], x)
            entry["y0"] = min(entry["y0"], y)
            entry["x1"] = max(entry["x1"], x + w)
            entry["y1"] = max(entry["y1"], y + h)
    out = []
    for entry in lines.values():
        text = " ".join(entry["words"]).strip()
        if not text:
            continue
        out.append({"text": text, "bbox": (entry["x0"], entry["y0"], entry["x1"], entry["y1"])})
    return out


def ingest_pdf(path: str, ocr_dpi: int = 220, min_text_chars_per_page: int = 40) -> Tuple[List[Chunk], IngestResult]:
    """Ingest one PDF file: try the real text layer per page, fall back to
    OCR on a per-page basis if that page looks image-only (this handles
    mixed PDFs where some pages have text and others are screenshots)."""
    warnings: List[str] = []
    method_counts: Dict[str, int] = {}
    chunks: List[Chunk] = []
    dashboard_name = _dashboard_name_from_path(path)
    abs_path = os.path.abspath(path)

    if fitz is None:
        warnings.append("PyMuPDF (fitz) not installed -- cannot read PDF at all.")
        return [], IngestResult(abs_path, dashboard_name, 0, 0, {}, warnings)

    try:
        doc = fitz.open(path)
    except Exception as e:
        warnings.append(f"Failed to open PDF: {e}")
        return [], IngestResult(abs_path, dashboard_name, 0, 0, {}, warnings)

    for page_index in range(len(doc)):
        page = doc[page_index]
        page_num = page_index + 1
        try:
            text_lines = _group_pdf_text_lines(page)
        except Exception as e:
            text_lines = []
            warnings.append(f"page {page_num}: text-layer extraction failed ({e})")

        total_chars = sum(len(l["text"]) for l in text_lines)

        if total_chars >= min_text_chars_per_page:
            method = "pdf_text_layer"
            lines = text_lines
        else:
            method = "ocr"
            lines = []
            if pytesseract is None or Image is None:
                warnings.append(
                    f"page {page_num}: no usable text layer and pytesseract/Pillow "
                    f"not installed -- page skipped (pip install pytesseract pillow, "
                    f"and make sure the tesseract binary is installed)."
                )
            else:
                try:
                    pix = page.get_pixmap(dpi=ocr_dpi)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    lines = _ocr_page_image(img, page_num)
                except Exception as e:
                    warnings.append(f"page {page_num}: OCR failed ({e})")

        method_counts[method] = method_counts.get(method, 0) + 1

        for line in lines:
            text = line["text"]
            chunks.append(Chunk(
                source_file=abs_path,
                dashboard_name=dashboard_name,
                page=page_num,
                text=text,
                bbox=tuple(round(v, 1) for v in line["bbox"]),
                extraction_method=method,
                metrics_found=_extract_metrics(text),
            ))

    doc.close()
    result = IngestResult(
        source_file=abs_path,
        dashboard_name=dashboard_name,
        pages=len(chunks) and (max(c.page for c in chunks)) or 0,
        chunks_added=len(chunks),
        extraction_method_summary=method_counts,
        warnings=warnings,
    )
    return chunks, result


def ingest_image(path: str) -> Tuple[List[Chunk], IngestResult]:
    """Ingest a single PNG/JPG screenshot dashboard via OCR."""
    warnings: List[str] = []
    abs_path = os.path.abspath(path)
    dashboard_name = _dashboard_name_from_path(path)

    if pytesseract is None or Image is None:
        warnings.append("pytesseract/Pillow not installed -- cannot OCR images.")
        return [], IngestResult(abs_path, dashboard_name, 0, 0, {}, warnings)

    try:
        img = Image.open(path).convert("RGB")
    except Exception as e:
        warnings.append(f"Failed to open image: {e}")
        return [], IngestResult(abs_path, dashboard_name, 0, 0, {}, warnings)

    try:
        lines = _ocr_page_image(img, 1)
    except Exception as e:
        warnings.append(f"OCR failed: {e}")
        lines = []

    chunks = [
        Chunk(
            source_file=abs_path,
            dashboard_name=dashboard_name,
            page=1,
            text=line["text"],
            bbox=tuple(round(v, 1) for v in line["bbox"]),
            extraction_method="ocr",
            metrics_found=_extract_metrics(line["text"]),
        )
        for line in lines
    ]
    result = IngestResult(
        source_file=abs_path,
        dashboard_name=dashboard_name,
        pages=1,
        chunks_added=len(chunks),
        extraction_method_summary={"ocr": 1} if chunks else {},
        warnings=warnings,
    )
    return chunks, result


def ingest_file(path: str, **kwargs) -> Tuple[List[Chunk], IngestResult]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return ingest_pdf(path, **kwargs)
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"):
        return ingest_image(path)
    return [], IngestResult(os.path.abspath(path), _dashboard_name_from_path(path), 0, 0, {},
                             [f"Unsupported file type: {ext}"])


# --------------------------------------------------------------------------
# Corpus persistence
# --------------------------------------------------------------------------

def load_corpus(corpus_path: str = DEFAULT_CORPUS_PATH) -> List[Chunk]:
    if not os.path.exists(corpus_path):
        return []
    with open(corpus_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [Chunk(**c) for c in raw]


def save_corpus(chunks: List[Chunk], corpus_path: str = DEFAULT_CORPUS_PATH) -> None:
    with open(corpus_path, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in chunks], f, indent=2)


def add_to_corpus(new_chunks: List[Chunk], corpus_path: str = DEFAULT_CORPUS_PATH) -> int:
    """Merge new_chunks into the persisted corpus, replacing any existing
    entries for the same source_file(s) so re-ingesting a file is a clean
    overwrite rather than an accumulating duplicate."""
    existing = load_corpus(corpus_path)
    touched_sources = {c.source_file for c in new_chunks}
    kept = [c for c in existing if c.source_file not in touched_sources]
    merged = kept + new_chunks
    save_corpus(merged, corpus_path)
    return len(merged)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    import argparse
    p = argparse.ArgumentParser(description="Ingest dashboard PDFs/images into a searchable corpus.")
    p.add_argument("files", nargs="+", help="One or more PDF/PNG/JPG dashboard files to ingest")
    p.add_argument("--corpus", default=DEFAULT_CORPUS_PATH, help="Corpus JSON path (default dashboard_corpus.json)")
    p.add_argument("--ocr-dpi", type=int, default=220, help="Rasterization DPI when a PDF page needs OCR")
    args = p.parse_args()

    total_chunks_before = len(load_corpus(args.corpus))
    for path in args.files:
        if not os.path.exists(path):
            print(f"[ingest] SKIP (not found): {path}")
            continue
        chunks, result = ingest_file(path, ocr_dpi=args.ocr_dpi)
        corpus_size = add_to_corpus(chunks, args.corpus)
        print(f"[ingest] {path}")
        print(f"         dashboard_name : {result.dashboard_name}")
        print(f"         pages          : {result.pages}")
        print(f"         chunks_added   : {result.chunks_added}")
        print(f"         methods        : {result.extraction_method_summary}")
        if result.warnings:
            for w in result.warnings:
                print(f"         warning        : {w}")
        print(f"         corpus_size_now: {corpus_size}")

    total_chunks_after = len(load_corpus(args.corpus))
    print(f"\n[ingest] Done. Corpus '{args.corpus}': {total_chunks_before} -> {total_chunks_after} chunks.")


if __name__ == "__main__":
    main()
