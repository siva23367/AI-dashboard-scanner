"""
Product Research module (live web search, not HTML heuristics)
----------------------------------------------------------------
Everything else in this scanner (scanner.py, pro_scanner.py, trust_signals.py,
web_vitals.py) is scoped to ONE page: whatever URL you pass in. None of it
answers "where else does this product show up on the internet" -- reviews,
other retailer listings, comparison articles, forum mentions, etc.

This module closes that gap. Given the product name/brand the scanner already
extracted from the page's schema.org Product data (or <title> as a fallback),
it runs a live web search and returns:

  - raw hits: title / url / snippet / domain for each result
  - classification of each hit into buckets: retailer listing, review/
    comparison site, video, forum/community, or "other mention"
  - any prices found inside the search snippets themselves (best-effort;
    this is NOT a price-comparison API, just text pattern matching on
    whatever text the search engine happened to return)
  - a short "reference_summary" narrative for the HTML/JSON report

Backends
--------
Default: DuckDuckGo's HTML endpoint (html.duckduckgo.com). No API key
required, but it's an unofficial scrape of a results page, so: keep result
counts modest, don't hammer it, and treat it as best-effort -- if DDG changes
markup or rate-limits you, this degrades to an empty result set rather than
crashing the whole scan (same "never break the core report" philosophy as
web_vitals.py).

Optional: pass --search-key (or set BING_SEARCH_KEY) to use the Bing Web
Search API instead, which is more reliable/higher-volume if you have a key.

Like web_vitals.py and revenue_impact.py, this is explicitly labeled as a
DIRECTIONAL / best-effort signal, not a guarantee of completeness or price
accuracy. It's a signal for the founder/researcher, not ground truth.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, quote_plus

import requests
from bs4 import BeautifulSoup

DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"

# Rough domain classification. Not exhaustive -- unknown domains fall back to
# "other mention", which is the honest default rather than a guess.
RETAILER_DOMAINS = {
    "amazon", "amazon.in", "flipkart", "walmart", "target", "bestbuy",
    "ebay", "etsy", "aliexpress", "myntra", "ajio", "croma", "reliancedigital",
    "shopify", "newegg", "costco", "samsung", "apple",
}
REVIEW_DOMAINS = {
    "trustpilot", "consumerreports", "rtings", "pcmag", "cnet", "techradar",
    "tomsguide", "wired", "theverge", "gsmarena", "91mobiles", "gadgets360",
    "digit.in", "androidauthority", "engadget",
}
VIDEO_DOMAINS = {"youtube", "youtu.be", "vimeo"}
FORUM_DOMAINS = {"reddit", "quora", "xda-developers", "stackexchange"}

PRICE_RE = re.compile(r"(?:₹|rs\.?|\$|€|£)\s?[\d][\d,]*(?:\.\d+)?", re.I)


def _root_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        host = host.split(":")[0]
        parts = host.split(".")
        # keep last two labels for things like "co.in" would need a public
        # suffix list to do perfectly; good-enough heuristic for our buckets.
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return ""


def _classify_domain(url: str) -> str:
    root = _root_domain(url)
    bare = root.split(".")[0]
    if bare in RETAILER_DOMAINS or root in RETAILER_DOMAINS:
        return "retailer_listing"
    if bare in REVIEW_DOMAINS or root in REVIEW_DOMAINS:
        return "review_or_comparison"
    if bare in VIDEO_DOMAINS or root in VIDEO_DOMAINS:
        return "video"
    if bare in FORUM_DOMAINS or root in FORUM_DOMAINS:
        return "forum_or_community"
    return "other_mention"


@dataclass
class ResearchHit:
    title: str
    url: str
    snippet: str
    domain: str
    bucket: str
    prices_found: List[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    query: str
    available: bool
    backend: str
    hits: List[ResearchHit] = field(default_factory=list)
    bucket_counts: Dict[str, int] = field(default_factory=dict)
    all_prices_found: List[str] = field(default_factory=list)
    reference_summary: List[str] = field(default_factory=list)
    error: Optional[str] = None


def _search_duckduckgo(query: str, num_results: int) -> List[Dict[str, str]]:
    resp = requests.post(
        DDG_HTML_ENDPOINT,
        data={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (compatible; SriyaProductResearch/1.0)"},
        timeout=12,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    out = []
    for res in soup.select("div.result")[: num_results * 2]:
        a = res.select_one("a.result__a")
        snip = res.select_one("a.result__snippet") or res.select_one("div.result__snippet")
        if not a or not a.get("href"):
            continue
        out.append({
            "title": a.get_text(" ", strip=True),
            "url": a["href"],
            "snippet": snip.get_text(" ", strip=True) if snip else "",
        })
        if len(out) >= num_results:
            break
    return out


def _search_bing(query: str, num_results: int, api_key: str) -> List[Dict[str, str]]:
    resp = requests.get(
        BING_ENDPOINT,
        params={"q": query, "count": num_results},
        headers={"Ocp-Apim-Subscription-Key": api_key},
        timeout=12,
    )
    resp.raise_for_status()
    data = resp.json()
    out = []
    for item in (data.get("webPages", {}).get("value") or [])[:num_results]:
        out.append({
            "title": item.get("name", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
        })
    return out


def research_product(product_name: str, brand: Optional[str] = None,
                      num_results: int = 8, api_key: Optional[str] = None,
                      extra_terms: Optional[str] = None) -> ResearchResult:
    """
    Live web search for a product's presence/mentions across the internet.
    Never raises -- on any failure (network, rate limit, markup change) it
    returns available=False with an error string, so a --research run never
    takes down the rest of the scan/report.
    """
    query = " ".join(x for x in [brand, product_name, extra_terms] if x).strip()
    if not query:
        return ResearchResult(query="", available=False, backend="none",
                               error="No product name/brand available to search for.")

    key = api_key or os.environ.get("BING_SEARCH_KEY")
    backend = "bing" if key else "duckduckgo"
    try:
        raw = _search_bing(query, num_results, key) if key else _search_duckduckgo(query, num_results)
    except Exception as e:
        return ResearchResult(query=query, available=False, backend=backend, error=str(e))

    hits: List[ResearchHit] = []
    bucket_counts: Dict[str, int] = {}
    all_prices: List[str] = []
    for r in raw:
        domain = _root_domain(r["url"])
        bucket = _classify_domain(r["url"])
        prices = list(dict.fromkeys(PRICE_RE.findall(r.get("snippet", ""))))
        hits.append(ResearchHit(title=r["title"], url=r["url"], snippet=r["snippet"],
                                 domain=domain, bucket=bucket, prices_found=prices))
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        all_prices.extend(prices)

    summary = []
    if hits:
        summary.append(f"Found {len(hits)} web reference(s) for \"{query}\" via {backend}.")
        for bucket, count in sorted(bucket_counts.items(), key=lambda x: -x[1]):
            label = bucket.replace("_", " ")
            summary.append(f"{count} {label} result(s).")
        if all_prices:
            uniq_prices = list(dict.fromkeys(all_prices))[:6]
            summary.append("Prices mentioned in search snippets: " + ", ".join(uniq_prices) +
                            " (best-effort text match, not a verified price feed).")
    else:
        summary.append(f"No web references found for \"{query}\" ({backend}). "
                        "Product may be new, region-locked, or the search backend rate-limited this request.")

    return ResearchResult(query=query, available=bool(hits), backend=backend, hits=hits,
                           bucket_counts=bucket_counts, all_prices_found=list(dict.fromkeys(all_prices)),
                           reference_summary=summary)


def to_dict(result: ResearchResult) -> Dict[str, Any]:
    return asdict(result)


def html_section_from_dict(d: Dict[str, Any]) -> str:
    """Same as html_section() but takes the plain dict shape produced by
    to_dict()/asdict() -- what pro_scanner.py actually stores on ProReport
    and serializes to JSON -- so callers don't need to reconstruct dataclasses."""
    from html import escape
    if not d:
        return ""
    if not d.get("available"):
        return (f'<section><h2>🔎 Product Research</h2>'
                 f'<p class="muted">No results ({escape(str(d.get("backend","")))}): '
                 f'{escape(str(d.get("error") or "no hits"))}</p></section>')
    rows = "".join(
        f'<tr><td>{escape(str(h.get("bucket","")).replace("_"," "))}</td>'
        f'<td><a href="{escape(h.get("url",""))}" target="_blank" rel="noopener">{escape(h.get("title",""))}</a>'
        f'<br><small>{escape(h.get("domain",""))}</small></td>'
        f'<td>{escape(h.get("snippet",""))}</td>'
        f'<td>{escape(", ".join(h.get("prices_found") or [])) or "-"}</td></tr>'
        for h in (d.get("hits") or [])
    )
    summary = "".join(f"<li>{escape(x)}</li>" for x in (d.get("reference_summary") or []))
    return f'''<section><h2>🔎 Product Research: web references for "{escape(d.get("query",""))}"</h2>
<p class="muted">Live search via {escape(str(d.get("backend","")))}. Directional signal only -- not a verified
price-comparison feed, and not a claim of completeness.</p>
<ul>{summary}</ul>
<table><tr><th>Type</th><th>Result</th><th>Snippet</th><th>Prices seen</th></tr>{rows}</table>
</section>'''


def html_section(result: ResearchResult) -> str:
    """Renders the same shape of HTML block pro_scanner.py's html_report()
    already uses for revenue_impact / web_vitals sections, so it drops in
    without touching the rest of the template."""
    from html import escape
    if not result:
        return ""
    if not result.available:
        return (f'<section><h2>🔎 Product Research</h2>'
                 f'<p class="muted">No results ({escape(result.backend)}): {escape(result.error or "no hits")}</p></section>')
    rows = "".join(
        f'<tr><td>{escape(h.bucket.replace("_"," "))}</td>'
        f'<td><a href="{escape(h.url)}" target="_blank" rel="noopener">{escape(h.title)}</a>'
        f'<br><small>{escape(h.domain)}</small></td>'
        f'<td>{escape(h.snippet)}</td>'
        f'<td>{escape(", ".join(h.prices_found)) if h.prices_found else "-"}</td></tr>'
        for h in result.hits
    )
    summary = "".join(f"<li>{escape(x)}</li>" for x in result.reference_summary)
    return f'''<section><h2>🔎 Product Research: web references for "{escape(result.query)}"</h2>
<p class="muted">Live search via {escape(result.backend)}. Directional signal only -- not a verified
price-comparison feed, and not a claim of completeness.</p>
<ul>{summary}</ul>
<table><tr><th>Type</th><th>Result</th><th>Snippet</th><th>Prices seen</th></tr>{rows}</table>
</section>'''
