from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlparse
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
from spellchecker import SpellChecker
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from rag import KnowledgeBase
from llm_judge import judge_spelling_issues, enrich_semantic_issues

# NOTE: the knowledge-base .txt files (semantic_html.txt, ecommerce_seo.txt,
# spelling_guidelines.txt) live in the SAME folder as this script, not in a
# "knowledge_base" subfolder. Previously KB_DIR pointed at a subfolder that
# never existed, so KnowledgeBase(KB_DIR) silently loaded 0 chunks every run
# -- the LLM was judging issues with no retrieved guidelines, i.e. the "RAG"
# part of "LLM + RAG" was doing nothing even though the console said
# "Enriching N semantic issue(s) with Groq + RAG context...".
KB_DIR = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class Issue:
    category: str          # "spelling" | "semantic"
    severity: str          # "error" | "warning" | "info"
    location: str          # e.g. "product title", "<img> #3"
    message: str
    original: Optional[str] = None
    suggestion: Optional[str] = None
    snippet: Optional[str] = None   # actual HTML at the issue location, for "where to fix"
    count: int = 1          # how many identical occurrences were collapsed into this entry


@dataclass
class ScanReport:
    url: str
    issues: List[Issue] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None
    # Kept for site-wide (--crawl) checks: duplicate-description detection
    # and catalog-wide price-currency consistency need this even though a
    # single-page report doesn't otherwise expose it.
    description: Optional[str] = None
    price_text: Optional[str] = None

    def add(self, *issues: Issue):
        self.issues.extend(issues)

    def summary(self) -> Dict[str, int]:
        s = {"error": 0, "warning": 0, "info": 0}
        for i in self.issues:
            s[i.severity] = s.get(i.severity, 0) + i.count
        return s


@dataclass
class SiteReport:
    """Aggregated result of scanning every page in a site's sitemap."""
    start_url: str
    sitemap_url: Optional[str] = None
    pages: List[ScanReport] = field(default_factory=list)
    failed: List[Dict[str, str]] = field(default_factory=list)  # {"url", "error"}
    skipped_count: int = 0  # non-PDP URLs (category pages, blog, etc.) skipped

    def summary(self) -> Dict[str, int]:
        s = {"error": 0, "warning": 0, "info": 0}
        for page in self.pages:
            if page.skipped:
                continue
            page_s = page.summary()
            for k in s:
                s[k] += page_s.get(k, 0)
        return s

    def scanned_pages(self) -> List["ScanReport"]:
        return [p for p in self.pages if not p.skipped]


# --------------------------------------------------------------------------
# 1. Fetcher
# --------------------------------------------------------------------------

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def fetch_html_static(url: str, timeout: int = 15) -> str:
    """Fast path: plain HTTP GET. Works for server-rendered pages."""
    session = requests.Session()
    resp = session.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    if resp.status_code == 403:
        retry_headers = dict(DEFAULT_HEADERS)
        retry_headers["Referer"] = "https://www.google.com/"
        resp = session.get(url, headers=retry_headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def fetch_html_rendered(url: str, timeout: int = 30) -> str:
    """
    Slow path: launches a real headless Chromium browser via Playwright and
    returns the DOM *after* JavaScript has run. Needed for SPA-style sites
    (Flipkart, Myntra, many modern React/Next.js storefronts) where the raw
    HTML from a plain HTTP GET is just an empty shell.

    Requires: pip install playwright && playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright is not installed. Run:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        ) from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=DEFAULT_HEADERS["User-Agent"])
        # "networkidle" is unreliable on sites with persistent background
        # requests (analytics, chat widgets, ad pixels) — the network never
        # goes fully quiet, causing false timeouts. "domcontentloaded" fires
        # much sooner and reliably; we then give the page a short grace
        # period for JS-rendered content (product data, etc.) to populate.
        try:
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        except Exception:
            # Even domcontentloaded can time out on very slow sites — fall
            # back to whatever loaded so far rather than failing outright.
            pass
        page.wait_for_timeout(4000)
        html = page.content()
        browser.close()
        return html


def _content_looks_empty(content: Dict[str, object]) -> bool:
    return not content.get("title") and not content.get("description") \
        and not content.get("bullets")


def fetch_and_extract(url: str, force_render: bool = False, timeout: int = 15) -> tuple:
    """
    Tries the fast static fetch first. If it fails outright (403/blocked) or
    the extracted content looks empty (a strong sign the page is JS-rendered),
    automatically retries with a real headless browser.
    Returns (soup, content, used_render: bool).
    """
    if not force_render:
        try:
            html = fetch_html_static(url, timeout=timeout)
            soup = BeautifulSoup(html, "lxml")
            content = extract_content(soup)
            if not _content_looks_empty(content):
                return soup, content, False
            print("[fetch] Static fetch returned little/no content — this page is likely "
                  "JavaScript-rendered. Retrying with a headless browser (Playwright)...",
                  file=sys.stderr)
        except requests.RequestException as e:
            print(f"[fetch] Static fetch failed ({e}). "
                  "Retrying with a headless browser (Playwright), which often bypasses "
                  "simple bot-blocking...", file=sys.stderr)

    html = fetch_html_rendered(url, timeout=max(timeout, 30))
    soup = BeautifulSoup(html, "lxml")
    content = extract_content(soup)
    return soup, content, True


# --------------------------------------------------------------------------
# 2. Content extraction (ecommerce-aware)
# --------------------------------------------------------------------------

# Common selector patterns used across ecommerce platforms (Shopify, Magento,
# WooCommerce, custom sites, schema.org itemprop attrs, etc.)
TITLE_SELECTORS = [
    "h1", "[itemprop='name']", ".product-title", ".product_title",
    "#productTitle", ".pdp-title",
]
DESC_SELECTORS = [
    "[itemprop='description']", ".product-description", ".product__description",
    "#productDescription", ".pdp-description", ".description",
]
BULLET_SELECTORS = [
    ".product-highlights li", "#feature-bullets li", ".pdp-highlights li",
    ".product-features li",
]
PRICE_SELECTORS = ["[itemprop='price']", ".price", ".product-price"]


def _first_match_text(soup: BeautifulSoup, selectors: List[str]) -> Optional[str]:
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(" ", strip=True)
    return None


def _all_match_text(soup: BeautifulSoup, selectors: List[str]) -> List[str]:
    out = []
    for sel in selectors:
        for el in soup.select(sel):
            txt = el.get_text(" ", strip=True)
            if txt:
                out.append(txt)
        if out:
            break
    return out


def _meta_content(soup: BeautifulSoup, *names: str) -> Optional[str]:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return None


def extract_content(soup: BeautifulSoup) -> Dict[str, object]:
    """
    E-commerce-only extraction: title, description, highlight bullets, and
    price. This tool is scoped exclusively to product pages (PDPs) — there
    is intentionally no generic-website fallback (no blog/social/body-text
    scraping). A page with none of these signals is treated as "not a
    product page" upstream (see is_product_page()) and skipped rather than
    scanned with weaker, off-scope heuristics.
    """
    title = _first_match_text(soup, TITLE_SELECTORS) or _meta_content(soup, "og:title") \
        or (soup.title.get_text(strip=True) if soup.title else None)
    description = _first_match_text(soup, DESC_SELECTORS) or _meta_content(soup, "og:description", "description")
    bullets = _all_match_text(soup, BULLET_SELECTORS)

    return {
        "title": title,
        "description": description,
        "bullets": bullets,
        "price_text": _first_match_text(soup, PRICE_SELECTORS),
    }


def has_product_schema(soup: BeautifulSoup) -> bool:
    """True if a schema.org Product JSON-LD block is present, regardless of
    whether it's complete — used as an extra product-page signal alongside
    price/bullets (some PDPs carry rich schema but a custom-CSS price widget
    our PRICE_SELECTORS list doesn't happen to match)."""
    for block in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(block.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if isinstance(c, dict) and c.get("@type") in ("Product", ["Product"]):
                return True
    return False


def is_product_page(soup: BeautifulSoup, content: Dict[str, object]) -> bool:
    """The single gate deciding whether a URL is in scope for this scanner:
    it must look like an actual product detail page (PDP) — has highlight
    bullets, a detected price, or Product schema.org markup. Category pages,
    cart/checkout, blog posts, and any non-PDP page are out of scope and get
    skipped rather than weakly scanned."""
    return bool(content.get("bullets") or content.get("price_text") or has_product_schema(soup))


# --------------------------------------------------------------------------
# 3. Spelling & grammar checks
# --------------------------------------------------------------------------

# Words that should never be flagged: brand/product/tech vocabulary common on
# ecommerce sites. Extend this list freely per client/catalog.
WHITELIST = {
    "bluetooth", "wifi", "usb", "hdmi", "ecommerce", "iphone", "ipad",
    "macbook", "android", "nike", "adidas", "puma", "samsung", "sony",
    "amazon", "flipkart", "myntra", "cashback", "checkout", "ml", "kg",
    "gb", "tb", "cm", "mm", "inch", "inches", "sku", "qty", "faq", "faqs",
    "smartwatch", "earbuds", "airpods", "4k", "led", "lcd", "oled",
    # Common British/Indian-English spellings (valid outside US English,
    # and this site's dictionary is US-English by default)
    "colour", "colours", "favourite", "favourites", "flavour", "flavours",
    "grey", "personalise", "personalised", "customise", "customised",
    "optimise", "optimised", "organise", "organised", "recognise",
    "recognised", "realise", "realised", "centre", "centres", "metre",
    "metres", "programme", "programmes", "labelled", "modelled",
    "travelled", "travelling", "cancelled", "jewellery",
    # Common laptop/PC spec vocabulary that dictionary spell-checkers don't
    # recognize but is standard on ecommerce electronics listings.
    "geforce", "nvidia", "amd", "radeon", "realtek", "srgb", "gbps",
    "mbps", "ghz", "mhz", "displayport", "hdmi", "pcie", "nvme", "ssd",
    "hdd", "ddr4", "ddr5", "gddr6", "backlit", "preinstalled", "xbox",
    "gamepass", "windows", "macos", "chromebook", "thunderbolt",
    "webcam", "trackpad", "touchpad", "fingerprint", "biometric",
    # Common tech-industry abbreviations/jargon that aren't regular English
    # derivations (so the morphological fallback below won't catch them).
    "dev", "devs", "repo", "repos", "backend", "frontend", "saas", "api",
    "apis", "sdk", "sdks", "webhook", "webhooks", "app", "apps",
}

WORD_RE = re.compile(r"[A-Za-z']+")

# Trailing possessive/contraction suffixes that trip up the dictionary
# (e.g. "Men's" is tokenized as "Men's" but the dictionary only knows "Men")
_POSSESSIVE_SUFFIX_RE = re.compile(r"'s$", re.IGNORECASE)


def _tokenize(text: str) -> List[str]:
    return WORD_RE.findall(text)


def _normalize_for_spellcheck(word: str) -> str:
    """Strip a trailing possessive/contraction ('s) before dictionary lookup,
    since "Men's", "Kid's" etc. are valid but the bare dictionary often
    doesn't recognize the apostrophe-s form."""
    return _POSSESSIVE_SUFFIX_RE.sub("", word)


# Suffixes that form a regular, valid English derivation from a known base
# word -- e.g. "analytics" ("analytic" + s), "agentic" ("agent" + ic),
# "shipping" ("ship" + ing). The dictionary's static word list often only
# contains the base form, not every inflection/derivation, so a hardcoded
# whitelist entry would be needed for every such word forever. Instead we
# check the base form generically: if it's a known word, the derived form
# is treated as valid too.
_DERIVATION_SUFFIXES = ["ically", "ical", "ally", "ing", "ers", "ied", "ies",
                        "er", "ic", "ed", "es", "s"]


def _is_valid_derived_word(word_lower: str, spell: SpellChecker) -> bool:
    for suf in _DERIVATION_SUFFIXES:
        if word_lower.endswith(suf) and len(word_lower) - len(suf) >= 3:
            base = word_lower[: -len(suf)]
            if base in spell:
                return True
    return False


def _is_compound_word(word_lower: str, spell: SpellChecker) -> bool:
    """Catches compounds like "workflow" (work + flow) that the dictionary
    doesn't list as a single entry but whose two halves are each valid
    words on their own -- common in product/marketing copy."""
    n = len(word_lower)
    for i in range(3, n - 2):
        left, right = word_lower[:i], word_lower[i:]
        if len(right) >= 3 and left in spell and right in spell:
            return True
    return False


def _detect_repeated_capitalized_words(content: Dict[str, object], min_repeats: int = 3) -> set:
    """A Title-Case word that shows up 3+ times across a page's visible text
    (nav, headings, footer, body copy, ...) is almost certainly the site's
    own brand/product name, not a random typo -- e.g. "Shopify" repeated
    12 times on shopify.com. We can't hardcode every site's brand name, but
    this generic frequency rule catches the pattern without one. All-caps
    acronyms are left alone since spell-checking already skips those."""
    counts: Dict[str, int] = {}
    fields: List[str] = []
    if content.get("title"):
        fields.append(content["title"])
    if content.get("description"):
        fields.append(content["description"])
    fields.extend(content.get("bullets") or [])

    for text in fields:
        for w in _tokenize(text):
            if len(w) > 2 and w[0].isupper() and not w.isupper():
                key = _normalize_for_spellcheck(w).lower()
                counts[key] = counts.get(key, 0) + 1

    return {w for w, c in counts.items() if c >= min_repeats}


def check_spelling(field_name: str, text: Optional[str], spell: SpellChecker,
                    brand_words: Optional[set] = None) -> List[Issue]:
    issues: List[Issue] = []
    if not text:
        return issues

    brand_words = brand_words or set()
    words = _tokenize(text)
    # Only check words with letters, skip pure numbers/short tokens/whitelist/brand names
    candidates = {
        w for w in words
        if len(w) > 2 and w.lower() not in WHITELIST and not w.isupper()
        and _normalize_for_spellcheck(w).lower() not in brand_words
    }
    if not candidates:
        return issues

    normalized = {w: _normalize_for_spellcheck(w) for w in candidates}
    misspelled = spell.unknown([normalized[w].lower() for w in candidates])
    # Drop anything that's actually a valid derived/compound word the base
    # dictionary just doesn't enumerate on its own (see helpers above).
    misspelled = {
        w for w in misspelled
        if not _is_valid_derived_word(w, spell) and not _is_compound_word(w, spell)
    }
    seen = set()
    for w in candidates:
        norm_lower = normalized[w].lower()
        if norm_lower in misspelled and norm_lower not in seen:
            seen.add(norm_lower)
            suggestion = spell.correction(norm_lower)
            # Grab the sentence/phrase containing the word for "where to fix" context
            idx = text.lower().find(w.lower())
            ctx_start = max(0, idx - 40)
            ctx_end = min(len(text), idx + len(w) + 40)
            context = ("..." if ctx_start > 0 else "") + text[ctx_start:ctx_end] + \
                      ("..." if ctx_end < len(text) else "")
            issues.append(Issue(
                category="spelling",
                severity="warning",
                location=field_name,
                message=f"Possible spelling mistake: '{w}'",
                original=w,
                suggestion=suggestion,
                snippet=context,
            ))
    return issues


def run_spelling_checks(content: Dict[str, object], catalog_brand_words: Optional[set] = None) -> List[Issue]:
    """catalog_brand_words: SKU/model/brand tokens learned from other product
    titles already seen in this catalog crawl (see scan_site) — on top of
    the per-page repeated-capitalized-word detection below, this lets a
    brand/model name that only appears once on THIS page (but repeatedly
    across the catalog) get whitelisted too, instead of relying solely on
    the LLM judge to catch it after the fact."""
    spell = SpellChecker()
    issues: List[Issue] = []
    brand_words = _detect_repeated_capitalized_words(content) | (catalog_brand_words or set())

    issues += check_spelling("page title", content.get("title"), spell, brand_words)
    issues += check_spelling("description", content.get("description"), spell, brand_words)

    for i, bullet in enumerate(content.get("bullets") or [], 1):
        issues += check_spelling(f"bullet point #{i}", bullet, spell, brand_words)

    return issues


def _title_brand_tokens(title: Optional[str]) -> set:
    """Capitalized tokens from a single product title, normalized for the
    spellchecker — the seed contribution this page adds to the catalog-wide
    brand/model whitelist used by later pages in the same crawl."""
    if not title:
        return set()
    return {
        _normalize_for_spellcheck(w).lower()
        for w in _tokenize(title)
        if len(w) > 2 and w[0].isupper() and not w.isupper()
    }


def dedupe_issues(issues: List[Issue]) -> List[Issue]:
    """Collapse issues that are identical apart from location/snippet into a
    single entry with a count, so a repeated UI component (e.g. the same
    'Buy now' carousel card appearing a dozen times on one page) doesn't
    drown out every other finding in the report. The first occurrence's
    location/snippet is kept as the representative example."""
    merged: Dict[tuple, Issue] = {}
    order: List[tuple] = []
    for issue in issues:
        key = (issue.category, issue.severity, issue.message, issue.original)
        if key in merged:
            merged[key].count += 1
        else:
            merged[key] = issue
            order.append(key)
    return [merged[k] for k in order]


# --------------------------------------------------------------------------
# 4. Semantic HTML checks (ecommerce-focused)
# --------------------------------------------------------------------------

def _snippet(tag, max_len: int = 220) -> str:
    """Raw HTML of a tag, truncated — shows exactly what to find/fix in the page source."""
    try:
        html = str(tag)
    except Exception:
        return ""
    return html if len(html) <= max_len else html[:max_len] + "..."


def check_headings(soup: BeautifulSoup) -> List[Issue]:
    issues = []
    h1s = soup.find_all("h1")
    if len(h1s) == 0:
        issues.append(Issue("semantic", "error", "<h1>",
                             "Page has no <h1>. Product title should be an <h1>."))
    elif len(h1s) > 1:
        issues.append(Issue("semantic", "warning", "<h1>",
                             f"Page has {len(h1s)} <h1> tags; there should be exactly one.",
                             snippet="\n".join(_snippet(h, 120) for h in h1s[:5])))

    heading_tags = soup.find_all(re.compile(r"^h[1-6]$"))
    levels = [(int(t.name[1]), t) for t in heading_tags]
    for (prev_lvl, prev_tag), (curr_lvl, curr_tag) in zip(levels, levels[1:]):
        if curr_lvl - prev_lvl > 1:
            issues.append(Issue("semantic", "warning", f"h{prev_lvl} -> h{curr_lvl}",
                                 "Heading level skipped (e.g. h2 followed directly by h4).",
                                 snippet=f"{_snippet(prev_tag, 100)}\n{_snippet(curr_tag, 100)}"))
    return issues


# Domains/patterns used almost exclusively for invisible 1x1 analytics/ad
# tracking pixels — not meaningful content images, so alt-text rules don't
# apply to them the way they do for product photos.
_TRACKING_PIXEL_PATTERNS = re.compile(
    r"facebook\.com/tr|google-analytics\.com|googletagmanager\.com|"
    r"doubleclick\.net|adservice\.google|analytics\.|/pixel\.|"
    r"track(?:ing)?[./]|beacon\.",
    re.I,
)


def _is_tracking_pixel(img) -> bool:
    src = img.get("src", "")
    if _TRACKING_PIXEL_PATTERNS.search(src):
        return True
    # Explicit 1x1 pixel dimensions are also a strong signal
    width, height = img.get("width"), img.get("height")
    if width in ("1", 1) and height in ("1", 1):
        return True
    return False


def check_images(soup: BeautifulSoup) -> List[Issue]:
    issues = []
    for i, img in enumerate(soup.find_all("img"), 1):
        if _is_tracking_pixel(img):
            continue  # invisible analytics pixel, not a content image
        alt = img.get("alt")
        src = img.get("src", "")
        if alt is None:
            issues.append(Issue("semantic", "error", f"<img> #{i} ({src[:40]})",
                                 "Missing alt attribute.", snippet=_snippet(img)))
        elif alt.strip() == "":
            continue  # explicitly decorative, acceptable
        elif re.search(r"\.(jpe?g|png|webp|gif)$", alt.strip(), re.I) or \
                re.match(r"^(img|image|photo)[\s_-]*\d*$", alt.strip(), re.I):
            issues.append(Issue("semantic", "warning", f"<img> #{i}",
                                 f"Non-descriptive alt text: '{alt}'. Use descriptive product alt text for SEO/accessibility.",
                                 snippet=_snippet(img)))
    return issues


def check_interactive_elements(soup: BeautifulSoup) -> List[Issue]:
    issues = []
    # divs/spans acting as buttons via onclick
    for i, el in enumerate(soup.find_all(["div", "span"], onclick=True), 1):
        text = el.get_text(strip=True)[:30]
        issues.append(Issue("semantic", "warning", f"<{el.name}> #{i} ('{text}')",
                             "Clickable element uses <div>/<span> with onclick instead of <button> or <a>. "
                             "Screen readers and keyboard users may not recognize it as interactive.",
                             snippet=_snippet(el, 180)))

    # anchors used as buttons with no href
    for i, a in enumerate(soup.find_all("a"), 1):
        if not a.get("href"):
            text = a.get_text(strip=True)[:30]
            issues.append(Issue("semantic", "info", f"<a> #{i} ('{text}')",
                                 "Anchor tag with no href — consider using <button> if it triggers an action.",
                                 snippet=_snippet(a, 150)))
    return issues


def check_schema_markup(soup: BeautifulSoup, is_product_page: bool = True) -> List[Issue]:
    issues = []
    ld_json_blocks = soup.find_all("script", type="application/ld+json")
    found_product_schema = False
    for block in ld_json_blocks:
        try:
            data = json.loads(block.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if isinstance(c, dict) and c.get("@type") in ("Product", ["Product"]):
                found_product_schema = True
                if "offers" not in c:
                    issues.append(Issue("semantic", "warning", "JSON-LD Product schema",
                                         "Product schema is missing 'offers' (price/availability) field.",
                                         snippet=json.dumps(c, indent=2)[:220]))
                if "aggregateRating" not in c and "review" not in c:
                    issues.append(Issue("semantic", "info", "JSON-LD Product schema",
                                         "No aggregateRating/review data in schema — missed rich-snippet opportunity.",
                                         snippet=json.dumps(c, indent=2)[:220]))
    # Only expect Product schema on pages that look like actual product pages
    # (has bullets/price). This scanner is PDP-only, so this should normally
    # always be true by the time this check runs.
    if is_product_page and not found_product_schema:
        issues.append(Issue("semantic", "warning", "JSON-LD",
                             "No schema.org Product structured data found. This hurts SEO rich results for ecommerce pages.",
                             snippet="<!-- Add a <script type=\"application/ld+json\"> block with @type: Product -->"))
    return issues


def check_buttons(soup: BeautifulSoup) -> List[Issue]:
    issues = []
    # Look for likely "Add to cart" text living in non-button/non-link tags
    add_to_cart_pattern = re.compile(r"add to (cart|bag)|buy now", re.I)
    for tag in soup.find_all(True):
        if tag.name in ("button", "a", "input"):
            continue
        text = tag.get_text(" ", strip=True)
        if text and add_to_cart_pattern.search(text) and len(text) < 40:
            # only flag if this tag has no button/a descendant handling it
            if not tag.find(["button", "a", "input"]):
                issues.append(Issue("semantic", "warning", f"<{tag.name}> ('{text[:30]}')",
                                     "Call-to-action text found outside a <button>/<a>/<input> element. "
                                     "Should be a real interactive element for accessibility & SEO.",
                                     snippet=_snippet(tag, 180)))

    # React/Vue/etc. attach click handlers via JS, not the onclick= HTML
    # attribute, so check_interactive_elements' onclick scan misses them.
    # A role="button" (or a plain <div>/<span>) that LOOKS clickable —
    # tabindex set, or cursor:pointer inline style, or a class name that
    # screams "button"/"btn" — but isn't a real <button>/<a> is the same
    # accessibility problem, just framework-rendered instead of inline JS.
    _CLICKABLE_CLASS_TOKENS = {"btn", "button"}
    for i, el in enumerate(soup.find_all(["div", "span"]), 1):
        if el.name in ("button", "a"):
            continue
        # If it already wraps a real interactive element (button/a[href]/
        # input/select/textarea), that descendant is what's keyboard- and
        # screen-reader-accessible — don't also flag the styling wrapper
        # around it, or every framework's "<span class=button><input/></span>"
        # pattern gets falsely flagged.
        if el.find(["button", "select", "textarea"]) is not None:
            continue
        if el.find("a", href=True) is not None:
            continue
        if el.find("input") is not None:
            continue
        role = (el.get("role") or "").lower()
        has_tabindex = el.get("tabindex") is not None
        style = el.get("style") or ""
        # Exact class-token match only (e.g. class="btn primary") — a
        # substring match would also hit label/wrapper classes like
        # "a-button-text" or "a-button-inner" that aren't themselves the
        # clickable element, causing heavy false positives on component
        # libraries (Amazon, Bootstrap, etc.) that use "button" in nested
        # naming for styling, not just the interactive root.
        class_tokens = {c.lower() for c in (el.get("class") or [])}
        has_cursor_pointer = ("cursor:pointer" in style.replace(" ", "")
                               or "cursor: pointer" in style)
        has_button_class = bool(class_tokens & _CLICKABLE_CLASS_TOKENS)

        # role="button" + tabindex is the correct WAI-ARIA custom-widget
        # pattern for making a non-native element keyboard-focusable and
        # correctly announced by screen readers -- this is the fix, not a
        # mistake, so it should never be flagged.
        if role == "button" and has_tabindex:
            continue

        # role="button" WITHOUT tabindex is a real, distinct problem: the
        # element is announced as a button but keyboard users can't
        # actually reach it with Tab.
        if role == "button":
            text = el.get_text(strip=True)[:30]
            issues.append(Issue(
                "semantic", "warning", f"<{el.name}> #{i} ('{text}')",
                "Element has role=\"button\" but no tabindex, so keyboard users "
                "can't focus it. Add tabindex=\"0\" to complete the ARIA "
                "custom-widget pattern.",
                snippet=_snippet(el, 180)))
            continue

        looks_styled_clickable = has_cursor_pointer or has_button_class or has_tabindex
        if looks_styled_clickable and el.get("onclick") is None:
            text = el.get_text(strip=True)[:30]
            issues.append(Issue(
                "semantic", "warning", f"<{el.name}> #{i} ('{text}')",
                "Element is styled/marked to look clickable (class/cursor/tabindex "
                "suggest it's a button) but has no role=\"button\" and isn't a real "
                "<button>/<a>. Common in React/Vue apps where the click handler is "
                "attached in JS, not as an onclick= attribute — still invisible to "
                "screen readers and keyboard users.",
                snippet=_snippet(el, 180)))
    return issues


# Words strongly associated with actual buttons/links (to avoid flagging
# every unlabeled <input> — search boxes, newsletter emails etc. often
# legitimately have no visible label but a placeholder instead).
_GENERIC_LINK_TEXT = {
    "click here", "here", "read more", "more", "link", "this link",
    "click", "learn more", "details", "more info", "go",
}


def check_forms(soup: BeautifulSoup) -> List[Issue]:
    """Form inputs need an accessible name: a <label for=id>, aria-label,
    aria-labelledby, or (weakest) a title/placeholder. Missing all of these
    means screen-reader users can't tell what the field is for."""
    issues = []
    labelled_ids = {lbl.get("for") for lbl in soup.find_all("label") if lbl.get("for")}

    for i, inp in enumerate(soup.find_all(["input", "textarea", "select"]), 1):
        itype = (inp.get("type") or "text").lower()
        if itype in ("hidden", "submit", "button", "image"):
            continue
        has_label = (
            inp.get("id") in labelled_ids
            or inp.get("aria-label")
            or inp.get("aria-labelledby")
            or (inp.find_parent("label") is not None)
        )
        if not has_label:
            severity = "warning" if (inp.get("placeholder") or inp.get("title")) else "error"
            issues.append(Issue(
                "semantic", severity, f"<{inp.name}> #{i} (type={itype})",
                "Form field has no associated <label>, aria-label, or aria-labelledby. "
                + ("Has a placeholder as a fallback, but placeholders disappear on input "
                   "and aren't a substitute for a real label."
                   if severity == "warning" else
                   "Screen-reader users get no indication of what this field is for."),
                snippet=_snippet(inp, 160)))
    return issues


def check_link_text(soup: BeautifulSoup) -> List[Issue]:
    """Flags <a> tags whose only accessible text is generic ('click here',
    'read more') — meaningless out of context for screen-reader users who
    often navigate a page via a list of link texts alone."""
    issues = []
    for i, a in enumerate(soup.find_all("a"), 1):
        if not a.get("href"):
            continue  # already covered by check_interactive_elements
        text = a.get_text(" ", strip=True).lower()
        has_aria = a.get("aria-label") or a.get("aria-labelledby")
        if text in _GENERIC_LINK_TEXT and not has_aria:
            issues.append(Issue(
                "semantic", "warning", f"<a> #{i} ('{a.get_text(strip=True)[:30]}')",
                f"Generic link text ('{a.get_text(strip=True)}') doesn't describe the "
                "destination. Screen-reader users often scan links out of context, and "
                "generic text also wastes SEO anchor-text value.",
                snippet=_snippet(a, 150)))
    return issues


def check_emphasis(soup: BeautifulSoup) -> List[Issue]:
    """<b>/<i> are purely visual (bold/italic styling); <strong>/<em> carry
    actual semantic meaning (importance/stress) that screen readers announce
    differently. Flags <b>/<i> used where the content is clearly meant to
    convey emphasis rather than just a visual style choice (heuristic: short,
    sentence-like text rather than e.g. a foreign-language phrase in <i>)."""
    issues = []
    for tag_name, correct in (("b", "strong"), ("i", "em")):
        for i, el in enumerate(soup.find_all(tag_name), 1):
            text = el.get_text(strip=True)
            if not text:
                continue
            issues.append(Issue(
                "semantic", "info", f"<{tag_name}> #{i} ('{text[:30]}')",
                f"<{tag_name}> is purely visual styling; if this text is meant to convey "
                f"importance/emphasis (not just a font style), use <{correct}> instead so "
                "screen readers announce it correctly.",
                snippet=_snippet(el, 120)))
    return issues


def check_lists(soup: BeautifulSoup) -> List[Issue]:
    """Catches manually 'bulleted' paragraphs (e.g. '<p>• Item one</p>'
    repeated back-to-back) that should be a real <ul>/<ol> so assistive tech
    announces list semantics (item count, position) instead of reading each
    line as an unrelated paragraph."""
    issues = []
    bullet_prefix = re.compile(r"^\s*[•\-\*–]\s+")
    siblings = soup.find_all("p")
    run = []
    for p in siblings:
        text = p.get_text(strip=True)
        if bullet_prefix.match(text):
            run.append(p)
        else:
            if len(run) >= 2:
                issues.append(Issue(
                    "semantic", "warning", f"<p> sequence ({len(run)} items)",
                    f"{len(run)} consecutive bullet-style <p> tags found — this should be a "
                    "real <ul><li> list, not manually bulleted paragraphs, so assistive tech "
                    "announces it as a list.",
                    snippet="\n".join(_snippet(p, 80) for p in run[:4])))
            run = []
    if len(run) >= 2:
        issues.append(Issue(
            "semantic", "warning", f"<p> sequence ({len(run)} items)",
            f"{len(run)} consecutive bullet-style <p> tags found — this should be a real "
            "<ul><li> list, not manually bulleted paragraphs, so assistive tech announces "
            "it as a list.",
            snippet="\n".join(_snippet(p, 80) for p in run[:4])))
    return issues


def check_tables(soup: BeautifulSoup) -> List[Issue]:
    """Data tables (e.g. size charts, spec comparisons — common on ecommerce
    PDPs) need <th> header cells (ideally with scope=) so screen readers can
    announce which row/column header a data cell belongs to. A <table> made
    entirely of <td> is a strong sign it's either a genuine accessibility
    miss, or (worse) a table being (mis)used purely for visual layout."""
    issues = []
    for i, table in enumerate(soup.find_all("table"), 1):
        ths = table.find_all("th")
        rows = table.find_all("tr")
        if len(rows) >= 2 and not ths:
            issues.append(Issue(
                "semantic", "warning", f"<table> #{i}",
                "Table has data rows but no <th> header cells — screen readers can't "
                "announce which column/row a cell's data belongs to (e.g. a size chart "
                "where 'M' needs to be understood as belonging to the 'Size' column).",
                snippet=_snippet(table, 200)))
        elif ths and not any(th.get("scope") for th in ths):
            issues.append(Issue(
                "semantic", "info", f"<table> #{i}",
                "Table has <th> cells but none use scope=\"col\"/\"row\" — adding scope "
                "removes ambiguity in tables with headers on both axes.",
                snippet=_snippet(table, 200)))
    return issues


MAX_META_TITLE_LEN = 60
MAX_META_DESC_LEN = 160
MIN_META_DESC_LEN = 70


def check_meta_tags(soup: BeautifulSoup) -> List[Issue]:
    """Title/meta-description hygiene — cheap, high-value SEO checks that
    were previously entirely absent. Long/short/missing meta description and
    <title> directly affect search snippet quality and click-through rate."""
    issues = []
    title_tag = soup.title.get_text(strip=True) if soup.title and soup.title.string else None
    if not title_tag:
        issues.append(Issue("semantic", "error", "<title>",
                             "Page is missing a <title> tag — this is the headline shown in search "
                             "results and browser tabs."))
    elif len(title_tag) > MAX_META_TITLE_LEN:
        issues.append(Issue("semantic", "warning", "<title>",
                             f"<title> is {len(title_tag)} characters — search engines typically "
                             f"truncate around {MAX_META_TITLE_LEN}. Shorten to avoid a cut-off snippet.",
                             snippet=title_tag))

    desc = _meta_content(soup, "description")
    if not desc:
        issues.append(Issue("semantic", "warning", "<meta name=\"description\">",
                             "Page has no meta description — search engines will auto-generate one "
                             "from page text instead, which is rarely as compelling as a written one."))
    elif len(desc) > MAX_META_DESC_LEN:
        issues.append(Issue("semantic", "info", "<meta name=\"description\">",
                             f"Meta description is {len(desc)} characters — likely to be truncated "
                             f"in search results (~{MAX_META_DESC_LEN} char limit).", snippet=desc))
    elif len(desc) < MIN_META_DESC_LEN:
        issues.append(Issue("semantic", "info", "<meta name=\"description\">",
                             f"Meta description is only {len(desc)} characters — likely too short to "
                             "make full use of the search snippet space.", snippet=desc))
    return issues


def check_canonical_robots(soup: BeautifulSoup, url: str) -> List[Issue]:
    """Canonical + robots meta hygiene on a PDP: a missing canonical invites
    duplicate-content issues (very common on ecommerce with ?color=/?size=
    variant query params), and an unexpected noindex/nofollow silently
    removes a live product page from search entirely."""
    issues = []
    canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    if not canonical or not canonical.get("href"):
        issues.append(Issue("semantic", "warning", "<link rel=\"canonical\">",
                             "No canonical tag found. Product pages with variant query params "
                             "(?color=, ?size=) risk being indexed as duplicate content without one."))

    robots = soup.find("meta", attrs={"name": "robots"})
    if robots:
        content = (robots.get("content") or "").lower()
        if "noindex" in content:
            issues.append(Issue("semantic", "error", "<meta name=\"robots\">",
                                 "Page is marked noindex — it will not appear in search results at all. "
                                 "Confirm this is intentional for a live product page.",
                                 snippet=_snippet(robots)))
    return issues


_OUT_OF_STOCK_PATTERN = re.compile(
    r"\bout of stock\b|\bsold out\b|\bcurrently unavailable\b|\bno longer available\b", re.I
)
_CART_CTA_PATTERN = re.compile(r"add to (cart|bag)|buy now", re.I)


def check_stock_status(soup: BeautifulSoup) -> List[Issue]:
    """Flags a PDP where out-of-stock/sold-out text is present but the
    Add-to-Cart/Buy-Now control still looks enabled — a direct trust and
    conversion problem: shoppers reach checkout only to find the item
    unavailable."""
    issues = []
    page_text = soup.get_text(" ", strip=True)
    if not _OUT_OF_STOCK_PATTERN.search(page_text):
        return issues

    for i, el in enumerate(soup.find_all(["button", "a", "input"]), 1):
        text = el.get_text(" ", strip=True) if el.name != "input" else (el.get("value") or "")
        if not text or not _CART_CTA_PATTERN.search(text):
            continue
        is_disabled = (
            el.get("disabled") is not None
            or (el.get("aria-disabled") or "").lower() == "true"
            or "disabled" in (el.get("class") or [])
        )
        if not is_disabled:
            issues.append(Issue(
                "semantic", "error", f"<{el.name}> #{i} ('{text[:30]}')",
                "Page text indicates the item is out of stock / sold out, but the Add to "
                "Cart / Buy Now control isn't marked disabled. Shoppers can attempt to buy "
                "an unavailable item.",
                snippet=_snippet(el, 160)))
    return issues


_RELATED_LINK_HINT = re.compile(r"related|recommend|similar|you.?may.?also.?like|cross.?sell", re.I)
MAX_LINKS_TO_CHECK = 12


def check_broken_cta_links(soup: BeautifulSoup, base_url: str, timeout: int = 6) -> List[Issue]:
    """Spot-checks the conversion-critical links on a PDP — the Add to Cart
    / Buy Now / Checkout control itself (when it's an <a href>) and nearby
    'related/recommended product' links — for 404s/5xxs. Bounded to
    MAX_LINKS_TO_CHECK requests so a single scan can't turn into a full
    link-crawl of the site."""
    from urllib.parse import urljoin

    issues = []
    candidates = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        is_cta = _CART_CTA_PATTERN.search(text or "")
        is_related = _RELATED_LINK_HINT.search(" ".join(a.get("class") or [])) or \
            (a.find_parent(class_=_RELATED_LINK_HINT) is not None)
        if is_cta or is_related:
            candidates.append((a, urljoin(base_url, a["href"])))
        if len(candidates) >= MAX_LINKS_TO_CHECK:
            break

    session = requests.Session()
    for a, link_url in candidates:
        if not link_url.startswith(("http://", "https://")):
            continue
        try:
            resp = session.head(link_url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
            if resp.status_code >= 405:  # some servers reject HEAD; retry with GET
                resp = session.get(link_url, headers=DEFAULT_HEADERS, timeout=timeout, stream=True)
            if resp.status_code >= 400:
                issues.append(Issue(
                    "semantic", "error", f"<a href=\"{link_url[:60]}\">",
                    f"Link returned HTTP {resp.status_code} — broken conversion-path or "
                    "related-product link.",
                    snippet=_snippet(a, 150)))
        except requests.RequestException as e:
            issues.append(Issue(
                "semantic", "warning", f"<a href=\"{link_url[:60]}\">",
                f"Could not verify this link ({e.__class__.__name__}) — check manually.",
                snippet=_snippet(a, 150)))
    return issues


_CURRENCY_SYMBOL_RE = re.compile(r"[$€£₹¥]|(?:USD|EUR|GBP|INR|JPY)\b")
_MALFORMED_PRICE_RE = re.compile(r"\d\.\d{3,}|\.\.|,,|\s{2,}")


def check_price_format(content: Dict[str, object]) -> List[Issue]:
    """Page-level price sanity check: flags a detected price string with no
    currency symbol/code at all, or with obviously malformed punctuation
    (double decimals, stray double commas/spaces from a bad template). Cross
    -page currency-symbol *consistency* across a whole catalog is checked
    separately in check_catalog_price_consistency() once a --crawl finishes."""
    issues = []
    price_text = content.get("price_text")
    if not price_text:
        return issues
    if not _CURRENCY_SYMBOL_RE.search(price_text):
        issues.append(Issue("semantic", "warning", "price",
                             f"Detected price text '{price_text}' has no recognizable currency "
                             "symbol or code (e.g. $, €, £, ₹, USD) — may confuse shoppers about "
                             "what currency they're being charged in.", snippet=price_text))
    if _MALFORMED_PRICE_RE.search(price_text):
        issues.append(Issue("semantic", "warning", "price",
                             f"Detected price text '{price_text}' looks malformed (stray punctuation "
                             "or spacing) — likely a template/formatting bug rather than a real price.",
                             snippet=price_text))
    return issues


def run_semantic_checks(soup: BeautifulSoup, url: str = "", is_product_page: bool = True,
                         check_links: bool = True) -> List[Issue]:
    issues: List[Issue] = []
    issues += check_headings(soup)
    issues += check_images(soup)
    issues += check_interactive_elements(soup)
    issues += check_schema_markup(soup, is_product_page=is_product_page)
    issues += check_buttons(soup)
    issues += check_forms(soup)
    issues += check_link_text(soup)
    issues += check_emphasis(soup)
    issues += check_lists(soup)
    issues += check_tables(soup)
    issues += check_meta_tags(soup)
    issues += check_canonical_robots(soup, url)
    issues += check_stock_status(soup)
    if check_links and url:
        issues += check_broken_cta_links(soup, url)
    return issues


# --------------------------------------------------------------------------
# 5. Orchestration
# --------------------------------------------------------------------------

def scan_url(url: str, use_llm: bool = True, force_render: bool = False,
             catalog_brand_words: Optional[set] = None, check_links: bool = True) -> ScanReport:
    """
    catalog_brand_words: a mutable set shared across a --crawl run. This
    scanner is e-commerce-only: a URL that doesn't look like a real product
    page (no bullets, no detected price, no Product schema) is skipped
    entirely rather than weakly scanned via a generic-content fallback.
    """
    report = ScanReport(url=url)

    soup, content, used_render = fetch_and_extract(url, force_render=force_render)
    if used_render:
        print("[fetch] Used headless-browser rendering for this page.", file=sys.stderr)

    if not is_product_page(soup, content):
        report.skipped = True
        report.skip_reason = ("Not a product page — no highlight bullets, detected price, or "
                               "Product schema.org markup found. This scanner is scoped to PDPs only.")
        print(f"[scan] Skipping {url}: {report.skip_reason}", file=sys.stderr)
        return report

    report.description = content.get("description")
    report.price_text = content.get("price_text")

    if _content_looks_empty(content):
        print("[warning] No usable text content found on this page even after rendering. "
              "It may require login, heavy interaction (infinite scroll/clicks), or block "
              "automated browsers outright — spelling checks will be skipped.", file=sys.stderr)

    spelling_issues = run_spelling_checks(content, catalog_brand_words=catalog_brand_words)
    semantic_issues = run_semantic_checks(soup, url=url, is_product_page=True, check_links=check_links)
    semantic_issues += check_price_format(content)

    if catalog_brand_words is not None:
        catalog_brand_words |= _title_brand_tokens(content.get("title"))

    if use_llm and os.environ.get("GROQ_API_KEY"):
        kb = KnowledgeBase(KB_DIR)
        print(f"[llm] Verifying {len(spelling_issues)} spelling flag(s) with Groq...")
        spelling_issues = judge_spelling_issues(spelling_issues, kb)
        print(f"[llm] Enriching {len(semantic_issues)} semantic issue(s) with Groq   + RAG context...")
        semantic_issues = enrich_semantic_issues(semantic_issues, kb)
    elif use_llm:
        print("[llm] GROQ_API_KEY not set — skipping LLM verification, "
              "showing rule-based results only.", file=sys.stderr)

    report.add(*dedupe_issues(spelling_issues))
    report.add(*dedupe_issues(semantic_issues))

    return report


# --------------------------------------------------------------------------
# 5b. Whole-site scanning (sitemap-driven crawl)
# --------------------------------------------------------------------------

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _fetch_text(url: str, timeout: int = 15) -> str:
    session = requests.Session()
    resp = session.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def discover_sitemap_url(site_url: str) -> Optional[str]:
    """Given any URL on a site, try to find that site's sitemap: first the
    conventional /sitemap.xml path, then robots.txt's 'Sitemap:' directive
    (the standard way sites advertise a non-default sitemap location)."""
    parsed = urlparse(site_url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    candidate = f"{root}/sitemap.xml"
    try:
        _fetch_text(candidate)
        return candidate
    except requests.RequestException:
        pass

    try:
        robots = _fetch_text(f"{root}/robots.txt")
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                return line.split(":", 1)[1].strip()
    except requests.RequestException:
        pass

    return None


def parse_sitemap_urls(sitemap_url: str, _depth: int = 0,
                        _seen: Optional[set] = None) -> List[str]:
    """Parses a sitemap.xml and returns the page URLs it lists. Sitemap
    *index* files (which just point at other sitemaps, common on large
    sites) are followed recursively, up to a small depth limit."""
    if _seen is None:
        _seen = set()
    if sitemap_url in _seen or _depth > 3:
        return []
    _seen.add(sitemap_url)

    try:
        xml_text = _fetch_text(sitemap_url)
    except requests.RequestException as e:
        print(f"[sitemap] Could not fetch {sitemap_url}: {e}", file=sys.stderr)
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"[sitemap] Could not parse {sitemap_url} as XML: {e}", file=sys.stderr)
        return []

    urls: List[str] = []
    if root.tag.lower().endswith("sitemapindex"):
        for sm in root.findall("sm:sitemap", _SITEMAP_NS) or root.findall("sitemap"):
            loc = sm.find("sm:loc", _SITEMAP_NS)
            if loc is None:
                loc = sm.find("loc")
            if loc is not None and loc.text:
                urls.extend(parse_sitemap_urls(loc.text.strip(), _depth + 1, _seen))
    else:
        for url_el in root.findall("sm:url", _SITEMAP_NS) or root.findall("url"):
            loc = url_el.find("sm:loc", _SITEMAP_NS)
            if loc is None:
                loc = url_el.find("loc")
            if loc is not None and loc.text:
                urls.append(loc.text.strip())

    return urls


DUPLICATE_DESCRIPTION_THRESHOLD = 0.85  # cosine similarity above which two PDP descriptions count as duplicates


def check_duplicate_descriptions(site_report: SiteReport) -> None:
    """
    ecommerce_seo.txt already documents that duplicate/near-duplicate
    product descriptions across a catalog hurt SEO ('treated as low-quality
    or duplicate content ... hurting rankings for all affected pages') —
    this implements that check using the same TF-IDF + cosine-similarity
    approach rag.py already uses for retrieval. Mutates site_report.pages
    in place, adding a "duplicate description" issue to each page in a
    matching pair.
    """
    pages_with_desc = [p for p in site_report.scanned_pages() if p.description]
    if len(pages_with_desc) < 2:
        return

    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        matrix = vectorizer.fit_transform([p.description for p in pages_with_desc])
    except ValueError:
        return  # e.g. every description was pure stop-words/empty after cleaning
    sims = cosine_similarity(matrix)

    flagged_pairs = set()
    for i in range(len(pages_with_desc)):
        for j in range(i + 1, len(pages_with_desc)):
            if sims[i, j] >= DUPLICATE_DESCRIPTION_THRESHOLD:
                flagged_pairs.add((i, j))

    for i, j in flagged_pairs:
        page_a, page_b = pages_with_desc[i], pages_with_desc[j]
        similarity_pct = round(sims[i, j] * 100)
        page_a.issues.append(Issue(
            "semantic", "warning", "description",
            f"Product description is {similarity_pct}% similar to {page_b.url} — near-duplicate "
            "content across PDPs can be treated as low-quality/duplicate content by search engines.",
            snippet=page_a.description[:200]))
        page_b.issues.append(Issue(
            "semantic", "warning", "description",
            f"Product description is {similarity_pct}% similar to {page_a.url} — near-duplicate "
            "content across PDPs can be treated as low-quality/duplicate content by search engines.",
            snippet=page_b.description[:200]))


def check_catalog_price_consistency(site_report: SiteReport) -> None:
    """Flags a catalog that mixes currency symbols/codes across PDPs
    (e.g. most products show '$' but a handful show '₹' or 'USD') — usually
    a locale-detection or template bug, not an intentional multi-currency
    catalog. Adds one info-level issue to each outlier page rather than
    guessing which currency is 'correct'."""
    pages_with_price = [p for p in site_report.scanned_pages() if p.price_text]
    if len(pages_with_price) < 3:
        return

    def _symbol(price_text: str) -> Optional[str]:
        m = _CURRENCY_SYMBOL_RE.search(price_text)
        return m.group(0).upper() if m else None

    symbol_counts: Dict[str, int] = {}
    for p in pages_with_price:
        sym = _symbol(p.price_text)
        if sym:
            symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
    if len(symbol_counts) < 2:
        return  # single currency (or none detected) across the catalog — nothing to flag

    majority_symbol = max(symbol_counts, key=symbol_counts.get)
    for p in pages_with_price:
        sym = _symbol(p.price_text)
        if sym and sym != majority_symbol:
            p.issues.append(Issue(
                "semantic", "info", "price",
                f"This page shows currency '{sym}' but {symbol_counts[majority_symbol]}/"
                f"{len(pages_with_price)} other scanned PDPs show '{majority_symbol}' — confirm "
                "this is an intentional multi-currency catalog, not a template/locale bug.",
                snippet=p.price_text))


def scan_site(start_url: str, max_pages: int = 20, use_llm: bool = True,
              force_render: bool = False, delay: float = 1.0,
              sitemap_url: Optional[str] = None) -> SiteReport:
    """Scans every page listed in a site's sitemap (discovered automatically
    from start_url's domain, or passed explicitly via sitemap_url), up to
    max_pages, and returns one aggregated SiteReport. If no sitemap can be
    found, falls back to scanning just start_url so this never scans zero
    pages."""
    site_report = SiteReport(start_url=start_url)

    if sitemap_url is None:
        print(f"[sitemap] Looking for a sitemap for {start_url} ...", file=sys.stderr)
        sitemap_url = discover_sitemap_url(start_url)

    if not sitemap_url:
        print("[sitemap] No sitemap.xml found (checked /sitemap.xml and robots.txt). "
              "Falling back to scanning just the one URL you gave.", file=sys.stderr)
        page_urls = [start_url]
    else:
        site_report.sitemap_url = sitemap_url
        print(f"[sitemap] Found sitemap: {sitemap_url}", file=sys.stderr)
        page_urls = parse_sitemap_urls(sitemap_url)
        if not page_urls:
            print("[sitemap] Sitemap had no page URLs in it. Falling back to "
                  "scanning just the one URL you gave.", file=sys.stderr)
            page_urls = [start_url]

    if len(page_urls) > max_pages:
        print(f"[sitemap] Sitemap lists {len(page_urls)} pages; scanning the first "
              f"{max_pages} (use --max-pages to change this).", file=sys.stderr)
        page_urls = page_urls[:max_pages]

    catalog_brand_words: set = set()  # grows as PDP titles are seen; see run_spelling_checks()

    for i, page_url in enumerate(page_urls, 1):
        print(f"\n[scan] ({i}/{len(page_urls)}) {page_url}", file=sys.stderr)
        try:
            page_report = scan_url(page_url, use_llm=use_llm, force_render=force_render,
                                    catalog_brand_words=catalog_brand_words)
            site_report.pages.append(page_report)
            if page_report.skipped:
                site_report.skipped_count += 1
        except Exception as e:
            print(f"[scan] Failed {page_url}: {e}", file=sys.stderr)
            site_report.failed.append({"url": page_url, "error": str(e)})
        if i < len(page_urls) and delay > 0:
            time.sleep(delay)

    print(f"\n[scan] Running catalog-wide checks (duplicate descriptions, "
          f"price-currency consistency) across {len(site_report.scanned_pages())} PDP(s)...",
          file=sys.stderr)
    check_duplicate_descriptions(site_report)
    check_catalog_price_consistency(site_report)

    return site_report


# --------------------------------------------------------------------------
# 6. Reporting
# --------------------------------------------------------------------------

def print_console_report(report: ScanReport):
    print(f"\nScan report for: {report.url}")

    if report.skipped:
        print(f"Skipped — {report.skip_reason}")
        return

    summary = report.summary()
    total = summary['error'] + summary['warning'] + summary['info']
    print(f"Total issues: {total}  "
          f"(errors: {summary['error']}, warnings: {summary['warning']}, info: {summary['info']})\n")

    if not report.issues:
        print("No issues found.")
        return

    by_category = {"spelling": [], "semantic": []}
    for issue in report.issues:
        by_category[issue.category].append(issue)

    for category, issues in by_category.items():
        if not issues:
            continue
        total = sum(i.count for i in issues)
        header = f"--- {category.upper()} ({len(issues)}"
        if total != len(issues):
            header += f", {total} occurrences"
        header += ") ---"
        print(header)
        for i in issues:
            tag = f"[{i.severity.upper()}]"
            line = f"  {tag:10} {i.location}: {i.message}"
            if i.count > 1:
                line += f"  (x{i.count})"
            if i.suggestion:
                line += f"  -> suggestion: '{i.suggestion}'"
            print(line)
            if i.snippet:
                snippet_oneline = " ".join(i.snippet.split())[:150]
                print(f"             where: {snippet_oneline}")
        print()
    print("Tip: run with --format html --out report.html for a browsable report "
          "with full HTML snippets showing exactly where to fix each issue.")


def _default_report_filename(url: str, ext: str = "json") -> str:
    """Builds a filename like 'shopify_com_20260811_143210.json' so repeated
    scans of different (or the same) sites don't silently overwrite each other."""
    host = urlparse(url).netloc or "site"
    host = re.sub(r"^www\.", "", host)
    host = re.sub(r"[^A-Za-z0-9]+", "_", host).strip("_") or "site"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{host}_{stamp}.{ext}"


def write_json_report(report: ScanReport, path: str):
    data = {
        "url": report.url,
        "skipped": report.skipped,
        "skip_reason": report.skip_reason,
        "summary": report.summary(),
        "issues": [asdict(i) for i in report.issues],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_csv_report(report: ScanReport, path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["category", "severity", "location",
                                                 "message", "original", "suggestion", "snippet", "count"])
        writer.writeheader()
        for i in report.issues:
            writer.writerow(asdict(i))


def _html_escape(s: Optional[str]) -> str:
    if not s:
        return ""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def _render_issue_rows_html(issues: List[Issue]) -> str:
    """Renders the shared per-issue HTML block used by both the single-page
    and whole-site HTML reports, so the two stay visually consistent."""
    sev_colors = {"error": "#d93025", "warning": "#e8710a", "info": "#1a73e8"}
    sev_order = {"error": 0, "warning": 1, "info": 2}
    sorted_issues = sorted(issues, key=lambda i: (sev_order.get(i.severity, 3), i.category))

    rows_html = []
    for issue in sorted_issues:
        color = sev_colors.get(issue.severity, "#5f6368")
        fix_html = ""
        if issue.suggestion:
            fix_html = f'<div class="fix"><strong>Suggested fix:</strong> {_html_escape(issue.suggestion)}</div>'
        snippet_html = ""
        if issue.snippet:
            snippet_html = f'<pre class="snippet">{_html_escape(issue.snippet)}</pre>'
        count_html = ""
        if issue.count > 1:
            count_html = f'<span class="category">&times;{issue.count} occurrences</span>'
        rows_html.append(f"""
        <div class="issue">
          <div class="issue-header">
            <span class="badge" style="background:{color}">{issue.severity.upper()}</span>
            <span class="category">{issue.category}</span>
            {count_html}
            <span class="location">{_html_escape(issue.location)}</span>
          </div>
          <div class="message">{_html_escape(issue.message)}</div>
          {snippet_html}
          {fix_html}
        </div>""")
    return "".join(rows_html)


_REPORT_CSS = """
  body { font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
          background: #f4f5f7; margin: 0; padding: 32px; color: #202124; }
  .container { max-width: 900px; margin: 0 auto; }
  h1 { font-size: 20px; word-break: break-all; }
  h2.page-heading { font-size: 16px; word-break: break-all; margin: 36px 0 4px;
                     padding-top: 20px; border-top: 1px solid #dadce0; }
  .summary { display: flex; gap: 16px; margin: 20px 0 28px; }
  .stat { background: #fff; border-radius: 8px; padding: 12px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .stat .num { font-size: 24px; font-weight: 700; }
  .stat .label { font-size: 12px; color: #5f6368; text-transform: uppercase; }
  .issue { background: #fff; border-radius: 8px; padding: 16px 20px; margin-bottom: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .issue-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .badge { color: #fff; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
  .category { font-size: 12px; color: #5f6368; text-transform: uppercase; letter-spacing: .04em; }
  .location { font-family: monospace; font-size: 13px; color: #333; margin-left: auto; }
  .message { font-size: 14px; line-height: 1.5; }
  .snippet { background: #f1f3f4; padding: 10px 12px; border-radius: 6px; font-size: 12px;
              overflow-x: auto; margin-top: 8px; white-space: pre-wrap; word-break: break-word; }
  .fix { font-size: 13px; margin-top: 8px; color: #137333; }
  .no-issues { background: #fff; padding: 24px; border-radius: 8px; text-align: center; color: #5f6368; }
  .toc { background: #fff; border-radius: 8px; padding: 16px 20px; margin-bottom: 28px;
          box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .toc a { display: block; font-size: 13px; padding: 4px 0; color: #1a73e8; text-decoration: none;
            word-break: break-all; }
  .toc a:hover { text-decoration: underline; }
"""


def write_html_report(report: ScanReport, path: str):
    """
    Writes a styled, self-contained HTML report: each issue shows what's
    wrong, exactly where in the page it is (HTML snippet / text context),
    and how to fix it — so it's actionable, not just a list of warnings.
    """
    summary = report.summary()
    rows_html = _render_issue_rows_html(report.issues)
    if report.skipped:
        rows_html = f'<div class="no-issues">Skipped — {_html_escape(report.skip_reason)}</div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Scan report — {_html_escape(report.url)}</title>
<style>{_REPORT_CSS}</style>
</head>
<body>
<div class="container">
  <h1>Scan report: {_html_escape(report.url)}</h1>
  <div class="summary">
    <div class="stat"><div class="num" style="color:#d93025">{summary.get('error', 0)}</div><div class="label">Errors</div></div>
    <div class="stat"><div class="num" style="color:#e8710a">{summary.get('warning', 0)}</div><div class="label">Warnings</div></div>
    <div class="stat"><div class="num" style="color:#1a73e8">{summary.get('info', 0)}</div><div class="label">Info</div></div>
  </div>
  {rows_html if rows_html else '<div class="no-issues">No issues found.</div>'}
</div>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# --------------------------------------------------------------------------
# 6b. Whole-site reporting
# --------------------------------------------------------------------------

def print_site_console_report(site_report: SiteReport):
    summary = site_report.summary()
    total = summary["error"] + summary["warning"] + summary["info"]
    print(f"\n{'=' * 70}")
    print(f"Site scan: {site_report.start_url}")
    if site_report.sitemap_url:
        print(f"Sitemap: {site_report.sitemap_url}")
    status = f"Pages scanned: {len(site_report.scanned_pages())}"
    if site_report.skipped_count:
        status += f"  (skipped, not a PDP: {site_report.skipped_count})"
    if site_report.failed:
        status += f"  (failed: {len(site_report.failed)})"
    print(status)
    print(f"Total issues across site: {total}  "
          f"(errors: {summary['error']}, warnings: {summary['warning']}, info: {summary['info']})")
    print(f"{'=' * 70}")

    for page in site_report.pages:
        print_console_report(page)

    if site_report.failed:
        print("\n--- PAGES THAT FAILED TO SCAN ---")
        for f in site_report.failed:
            print(f"  {f['url']}: {f['error']}")


def write_site_json_report(site_report: SiteReport, path: str):
    data = {
        "start_url": site_report.start_url,
        "sitemap_url": site_report.sitemap_url,
        "summary": site_report.summary(),
        "skipped_count": site_report.skipped_count,
        "pages": [
            {"url": p.url, "skipped": p.skipped, "skip_reason": p.skip_reason,
             "summary": p.summary(), "issues": [asdict(i) for i in p.issues]}
            for p in site_report.pages
        ],
        "failed": site_report.failed,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_site_csv_report(site_report: SiteReport, path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["page_url", "category", "severity", "location",
                                                 "message", "original", "suggestion", "snippet", "count"])
        writer.writeheader()
        for page in site_report.pages:
            for i in page.issues:
                row = asdict(i)
                row["page_url"] = page.url
                writer.writerow(row)


def write_site_html_report(site_report: SiteReport, path: str):
    """One combined HTML report covering every scanned page, with a
    jump-to-page table of contents at the top followed by a section per
    page (reusing the same issue-card rendering as the single-page report)."""
    summary = site_report.summary()

    toc_html = "".join(
        f'<a href="#page-{idx}">{_html_escape(p.url)} '
        f'({"skipped, not a PDP" if p.skipped else f"{sum(p.summary().values())} issues"})</a>'
        for idx, p in enumerate(site_report.pages)
    )

    page_sections = []
    for idx, page in enumerate(site_report.pages):
        if page.skipped:
            page_sections.append(f"""
            <h2 class="page-heading" id="page-{idx}">{_html_escape(page.url)}</h2>
            <div class="no-issues">Skipped — {_html_escape(page.skip_reason)}</div>
            """)
            continue
        page_summary = page.summary()
        rows_html = _render_issue_rows_html(page.issues)
        page_sections.append(f"""
        <h2 class="page-heading" id="page-{idx}">{_html_escape(page.url)}</h2>
        <div class="summary">
          <div class="stat"><div class="num" style="color:#d93025">{page_summary.get('error', 0)}</div><div class="label">Errors</div></div>
          <div class="stat"><div class="num" style="color:#e8710a">{page_summary.get('warning', 0)}</div><div class="label">Warnings</div></div>
          <div class="stat"><div class="num" style="color:#1a73e8">{page_summary.get('info', 0)}</div><div class="label">Info</div></div>
        </div>
        {rows_html if rows_html else '<div class="no-issues">No issues found on this page.</div>'}
        """)

    failed_html = ""
    if site_report.failed:
        items = "".join(
            f'<div class="issue"><div class="message">{_html_escape(f["url"])} — {_html_escape(f["error"])}</div></div>'
            for f in site_report.failed
        )
        failed_html = f'<h2 class="page-heading">Pages that failed to scan</h2>{items}'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Site scan report — {_html_escape(site_report.start_url)}</title>
<style>{_REPORT_CSS}</style>
</head>
<body>
<div class="container">
  <h1>Site scan: {_html_escape(site_report.start_url)}</h1>
  <div class="summary">
    <div class="stat"><div class="num" style="color:#d93025">{summary.get('error', 0)}</div><div class="label">Errors</div></div>
    <div class="stat"><div class="num" style="color:#e8710a">{summary.get('warning', 0)}</div><div class="label">Warnings</div></div>
    <div class="stat"><div class="num" style="color:#1a73e8">{summary.get('info', 0)}</div><div class="label">Info</div></div>
  </div>
  <div class="toc"><strong>Pages scanned ({len(site_report.pages)}):</strong>{toc_html}</div>
  {"".join(page_sections)}
  {failed_html}
</div>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scan e-commerce product pages (PDPs) for spelling and semantic HTML mistakes. Non-product pages (category listings, blog, cart, etc.) are detected and skipped."
    )
    parser.add_argument("url", nargs="?", help="Page URL to scan (or any URL on the site, when using --crawl)")
    parser.add_argument("--format", choices=["console", "json", "csv", "html"], default="console")
    parser.add_argument("--out", help="Output file path (required for json/csv/html format)")
    parser.add_argument("--no-llm", action="store_true",
                         help="Skip LLM/RAG verification even if GEMINI_API_KEY is set")
    parser.add_argument("--render", action="store_true",
                         help="Force headless-browser (Playwright) rendering instead of "
                              "auto-detecting. Use this for known JS-heavy storefronts "
                              "(Flipkart, Myntra, many React/Next.js storefronts, etc.) to skip the slower auto-retry step.")
    parser.add_argument("--crawl", action="store_true",
                         help="Scan the whole site, not just one page. Auto-discovers the "
                              "site's sitemap.xml (via /sitemap.xml or robots.txt) from the "
                              "URL you give and scans every page it lists.")
    parser.add_argument("--sitemap", metavar="URL",
                         help="Explicit sitemap.xml URL to crawl from, if it's not at the "
                              "default location. Implies --crawl.")
    parser.add_argument("--max-pages", type=int, default=20,
                         help="Max number of pages to scan in --crawl mode (default: 20).")
    parser.add_argument("--delay", type=float, default=1.0,
                         help="Seconds to wait between page scans in --crawl mode, to avoid "
                              "hammering the site (default: 1.0).")
    args = parser.parse_args()

    url = args.url or input("Enter website URL to scan: ").strip()
    crawl = args.crawl or bool(args.sitemap)

    try:
        if crawl:
            site_report = scan_site(url, max_pages=args.max_pages, use_llm=not args.no_llm,
                                     force_render=args.render, delay=args.delay,
                                     sitemap_url=args.sitemap)
        else:
            report = scan_url(url, use_llm=not args.no_llm, force_render=args.render)
    except requests.RequestException as e:
        print(f"Failed to fetch URL: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # Catches Playwright-specific errors (TimeoutError, target closed, etc.)
        # without needing to import its exception types directly.
        print(f"Failed to load page even with headless-browser rendering: {e}", file=sys.stderr)
        print("This site may be actively blocking automated browsers (Cloudflare/Akamai "
              "bot challenges), require login, or the URL may be invalid.", file=sys.stderr)
        sys.exit(1)

    if crawl:
        print_site_console_report(site_report)

        json_out = args.out if args.format == "json" and args.out else _default_report_filename(url, "json")
        write_site_json_report(site_report, json_out)
        print(f"\n[report] Full JSON report auto-saved to: {os.path.abspath(json_out)}")

        if args.format == "csv":
            out = args.out or _default_report_filename(url, "csv")
            write_site_csv_report(site_report, out)
            print(f"[report] CSV report written to: {os.path.abspath(out)}")
        elif args.format == "html":
            out = args.out or _default_report_filename(url, "html")
            write_site_html_report(site_report, out)
            print(f"[report] HTML report written to: {os.path.abspath(out)} — open it in your browser to view.")
        return

    # Always show the console summary, regardless of --format.
    print_console_report(report)

    # Always auto-save a JSON report too (this is the "downloadable" copy
    # with every issue + exact location + suggestion), so you never have to
    # remember to pass --format json to get a file out of a scan.
    json_out = args.out if args.format == "json" and args.out else _default_report_filename(url, "json")
    write_json_report(report, json_out)
    print(f"\n[report] Full JSON report auto-saved to: {os.path.abspath(json_out)}")

    # If a different format was explicitly requested, write that too
    # (in addition to, not instead of, the JSON file above).
    if args.format == "csv":
        out = args.out or _default_report_filename(url, "csv")
        write_csv_report(report, out)
        print(f"[report] CSV report written to: {os.path.abspath(out)}")
    elif args.format == "html":
        out = args.out or _default_report_filename(url, "html")
        write_html_report(report, out)
        print(f"[report] HTML report written to: {os.path.abspath(out)} — open it in your browser to view.")


if __name__ == "__main__":
    main()