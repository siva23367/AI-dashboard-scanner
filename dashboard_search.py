from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from dashboard_ingest import Chunk, load_corpus, DEFAULT_CORPUS_PATH

try:
    from google import genai
except ImportError:
    genai = None

MODEL = os.environ.get("Groq_MODEL", "gemini-3.6-flash")

PROXIMITY_WINDOW = 140.0  # layout units (~pixels at typical OCR dpi)


@dataclass
class MatchedChunk:
    text: str
    dashboard_name: str
    page: int
    source_file: str
    match_type: str          # "exact" or "semantic"
    score: float             # 1.0 for exact, cosine similarity for semantic
    metrics_found: List[str] = field(default_factory=list)


@dataclass
class SearchResult:
    query: str
    matched_chunks: List[MatchedChunk] = field(default_factory=list)
    surrounding_chunks: List[MatchedChunk] = field(default_factory=list)
    dashboards_hit: List[str] = field(default_factory=list)
    all_metrics_found: List[str] = field(default_factory=list)
    ai_answer: Optional[str] = None
    ai_answer_available: bool = False
    web_enrichment: Optional[Dict[str, Any]] = None


class DashboardIndex:
    """In-memory semantic index over an ingested dashboard corpus."""

    def __init__(self, corpus_path: str = DEFAULT_CORPUS_PATH):
        self.corpus_path = corpus_path
        self.chunks: List[Chunk] = load_corpus(corpus_path)
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._matrix = None
        if self.chunks:
            self._vectorizer = TfidfVectorizer(stop_words="english")
            self._matrix = self._vectorizer.fit_transform([c.text for c in self.chunks])

    def is_empty(self) -> bool:
        return not self.chunks

    # -- matching -----------------------------------------------------

    def _exact_matches(self, query: str) -> List[MatchedChunk]:
        q = query.lower().strip()
        if not q:
            return []
        out = []
        for c in self.chunks:
            if q in c.text.lower():
                out.append(MatchedChunk(
                    text=c.text, dashboard_name=c.dashboard_name, page=c.page,
                    source_file=c.source_file, match_type="exact", score=1.0,
                    metrics_found=c.metrics_found,
                ))
        return out

    def _semantic_matches(self, query: str, top_k: int = 8, min_score: float = 0.08) -> List[MatchedChunk]:
        if self._matrix is None or self._vectorizer is None:
            return []
        query_vec = self._vectorizer.transform([query])
        sims = cosine_similarity(query_vec, self._matrix)[0]
        ranked_idx = sims.argsort()[::-1][:top_k]
        out = []
        for i in ranked_idx:
            if sims[i] <= min_score:
                continue
            c = self.chunks[i]
            out.append(MatchedChunk(
                text=c.text, dashboard_name=c.dashboard_name, page=c.page,
                source_file=c.source_file, match_type="semantic", score=round(float(sims[i]), 4),
                metrics_found=c.metrics_found,
            ))
        return out

    # -- surrounding-data retrieval -------------------------------------

    def _surrounding(self, matched: List[MatchedChunk], window: float = PROXIMITY_WINDOW) -> List[MatchedChunk]:
        """For every matched chunk, find other chunks on the same page of
        the same dashboard whose bounding box center is within `window`
        layout units, so we recover the label/value pairs that sit next
        to the matched text on the original dashboard card/table."""
        matched_keys = {(m.source_file, m.page, m.text) for m in matched}
        # Build a lookup of bbox by (source_file, page, text) from the
        # original corpus so we have geometry, not just the matched text.
        bbox_lookup: Dict[tuple, tuple] = {
            (c.source_file, c.page, c.text): c.bbox for c in self.chunks
        }

        out: List[MatchedChunk] = []
        seen = set(matched_keys)
        for m in matched:
            key = (m.source_file, m.page, m.text)
            box = bbox_lookup.get(key)
            if box is None:
                continue
            mx = (box[0] + box[2]) / 2
            my = (box[1] + box[3]) / 2
            for c in self.chunks:
                if c.source_file != m.source_file or c.page != m.page:
                    continue
                ckey = (c.source_file, c.page, c.text)
                if ckey in seen:
                    continue
                cx = (c.bbox[0] + c.bbox[2]) / 2
                cy = (c.bbox[1] + c.bbox[3]) / 2
                dist = ((cx - mx) ** 2 + (cy - my) ** 2) ** 0.5
                if dist <= window:
                    out.append(MatchedChunk(
                        text=c.text, dashboard_name=c.dashboard_name, page=c.page,
                        source_file=c.source_file, match_type="surrounding",
                        score=round(1.0 - min(dist / window, 1.0), 3),
                        metrics_found=c.metrics_found,
                    ))
                    seen.add(ckey)
        return out

    # -- public entry point ---------------------------------------------

    def search(self, query: str, use_semantic_fallback: bool = True, include_surrounding: bool = True) -> SearchResult:
        exact = self._exact_matches(query)
        matched = exact
        if not matched and use_semantic_fallback:
            matched = self._semantic_matches(query)
        elif use_semantic_fallback:
            # Even with exact hits, pull in a couple of semantic near-misses
            # (e.g. "iPhone" query when the dashboard says "iPhone 15 Pro").
            existing_texts = {m.text for m in matched}
            for sm in self._semantic_matches(query, top_k=4):
                if sm.text not in existing_texts:
                    matched.append(sm)

        surrounding = self._surrounding(matched) if include_surrounding else []

        dashboards_hit = sorted({m.dashboard_name for m in matched} | {s.dashboard_name for s in surrounding})
        all_metrics: List[str] = []
        for m in matched + surrounding:
            for metric in m.metrics_found:
                if metric not in all_metrics:
                    all_metrics.append(metric)

        return SearchResult(
            query=query,
            matched_chunks=matched,
            surrounding_chunks=surrounding,
            dashboards_hit=dashboards_hit,
            all_metrics_found=all_metrics,
        )


# --------------------------------------------------------------------------
# LLM summarization (same fallback contract as llm_judge.py)
# --------------------------------------------------------------------------

def _get_client():
    if genai is None:
        return None
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def _short_error(e: Exception) -> str:
    msg = str(e)
    match = re.search(r"'message':\s*'([^']+)'", msg)
    if match:
        msg = match.group(1)
    return msg[:200]


def summarize_with_llm(result: SearchResult) -> SearchResult:
    """Ask Gemini to turn the structured findings into a short "AI Answer"
    paragraph. Silently leaves result.ai_answer as None (with
    ai_answer_available=False) if no API key is set or the call fails --
    the structured data in `result` is still fully usable without this."""
    client = _get_client()
    if client is None:
        return result
    if not result.matched_chunks and not result.surrounding_chunks:
        return result

    lines = [f'Query: "{result.query}"', f"Dashboards containing matches: {', '.join(result.dashboards_hit) or 'none'}"]
    lines.append("\nMatched text:")
    for m in result.matched_chunks[:15]:
        lines.append(f"- [{m.dashboard_name} p{m.page}, {m.match_type} match {m.score}] {m.text}")
    lines.append("\nSurrounding context on the same cards/tables:")
    for s in result.surrounding_chunks[:25]:
        lines.append(f"- [{s.dashboard_name} p{s.page}] {s.text}")
    if result.web_enrichment:
        lines.append("\nLive web references found for this product:")
        lines.append(json.dumps(result.web_enrichment, ensure_ascii=False)[:2000])

    system = (
        "You are summarizing search results pulled from internal business "
        "dashboards (screenshots/PDF exports that were OCR'd). Write a short, "
        "factual answer to the query using ONLY the matched text and "
        "surrounding context provided. State which dashboard(s) the "
        "information came from. If the matched data is ambiguous or "
        "incomplete, say so plainly instead of guessing. Do not invent "
        "numbers that are not present in the provided context. 4-8 sentences."
    )
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=f"{system}\n\n" + "\n".join(lines),
            config={"temperature": 0.2},
        )
        text = (resp.text or "").strip()
        if text:
            result.ai_answer = text
            result.ai_answer_available = True
    except Exception:
        # Same silent-fallback contract as llm_judge.py -- structured data
        # is still returned; we just don't get the prose summary.
        pass
    return result


# --------------------------------------------------------------------------
# Optional live web enrichment via product_research.py
# --------------------------------------------------------------------------

def enrich_with_web_research(query: str, num_results: int = 6) -> Optional[Dict[str, Any]]:
    """Reuses the existing product_research.py module to answer "what does
    the live web say about this product" alongside "what do our internal
    dashboards say" -- same directional/best-effort caveat as that module."""
    try:
        import product_research
    except ImportError:
        return None
    try:
        rr = product_research.research_product(query, brand=None, num_results=num_results)
        return product_research.to_dict(rr)
    except Exception as e:
        return {"available": False, "error": _short_error(e)}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def to_dict(result: SearchResult) -> Dict[str, Any]:
    return asdict(result)


def main():
    import argparse
    p = argparse.ArgumentParser(description="Search ingested dashboards for a product/entity and its surrounding data.")
    p.add_argument("query", help='e.g. "Samsung Galaxy S24" or "iPhone 15"')
    p.add_argument("--corpus", default=DEFAULT_CORPUS_PATH, help="Corpus JSON path (default dashboard_corpus.json)")
    p.add_argument("--no-semantic", action="store_true", help="Disable TF-IDF semantic fallback, exact match only")
    p.add_argument("--no-surrounding", action="store_true", help="Don't pull in nearby cards/labels, matched text only")
    p.add_argument("--summarize", action="store_true", help="Also call Gemini for a natural-language AI Answer")
    p.add_argument("--research", action="store_true", help="Also run live web research on this query via product_research.py")
    p.add_argument("--out", default=None, help="Optional path to write the full JSON result")
    args = p.parse_args()

    index = DashboardIndex(args.corpus)
    if index.is_empty():
        print(f"[search] Corpus '{args.corpus}' is empty or missing.")
        print(f"[search] Ingest dashboards first: python dashboard_ingest.py your_dashboard.pdf --corpus {args.corpus}")
        return

    result = index.search(
        args.query,
        use_semantic_fallback=not args.no_semantic,
        include_surrounding=not args.no_surrounding,
    )

    if args.research:
        result.web_enrichment = enrich_with_web_research(args.query)

    if args.summarize:
        result = summarize_with_llm(result)

    print(f'\n=== Search: "{args.query}" ===')
    if not result.matched_chunks:
        print("No matches found in the ingested dashboard corpus (exact or semantic).")
    else:
        print(f"Dashboards hit: {', '.join(result.dashboards_hit)}")
        print(f"\nMatched text ({len(result.matched_chunks)}):")
        for m in result.matched_chunks:
            print(f"  [{m.dashboard_name} p{m.page} | {m.match_type} {m.score}] {m.text}")
        if result.surrounding_chunks:
            print(f"\nSurrounding data ({len(result.surrounding_chunks)}):")
            for s in result.surrounding_chunks:
                print(f"  [{s.dashboard_name} p{s.page}] {s.text}")
        if result.all_metrics_found:
            print(f"\nNumeric/metric values found: {', '.join(result.all_metrics_found)}")

    if result.web_enrichment:
        print(f"\nLive web research: {json.dumps(result.web_enrichment, ensure_ascii=False)[:500]}...")

    if result.ai_answer_available:
        print(f"\nAI Answer:\n{result.ai_answer}")
    elif args.summarize:
        print("\nAI Answer: unavailable (no GEMINI_API_KEY set, or the call failed/quota-limited) -- structured results above are unaffected.")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(to_dict(result), f, indent=2, ensure_ascii=False)
        print(f"\nFull JSON written to {args.out}")


if __name__ == "__main__":
    main()
