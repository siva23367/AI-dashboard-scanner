"""
Core Web Vitals module (real data, not heuristics)
---------------------------------------------------
The existing performance_audit() in pro_scanner.py is a static HTML heuristic
(counts lazy-loading attrs, script tags, etc). It's useful but it is NOT what
Google actually ranks on and it is NOT what a founder's board deck should
quote. This module calls the Google PageSpeed Insights v5 API (Lighthouse +
real Chrome UX Report field data where available) to pull the actual metrics
Google uses for the "Core Web Vitals" ranking signal and for real-world
mobile/desktop experience:

  - LCP  (Largest Contentful Paint)  -> perceived load speed
  - CLS  (Cumulative Layout Shift)   -> visual stability
  - INP  (Interaction to Next Paint) -> responsiveness (replaced FID in 2024)
  - TTFB (Time to First Byte)        -> server/backend speed
  - Lighthouse performance score (0-100)

No API key is required for light usage (Google rate-limits by IP instead),
but you can set PSI_API_KEY (or pass --psi-key) to raise the quota.

This is intentionally a separate module from pro_scanner.py's static
performance_audit() -- both are kept, and both are reported, so a founder
can see "what our HTML suggests" vs "what Google actually measured".
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# Official Google thresholds (web.dev/vitals, 2024-2025 revision incl. INP).
THRESHOLDS = {
    "LARGEST_CONTENTFUL_PAINT_MS": {"good": 2500, "poor": 4000, "unit": "ms", "label": "LCP"},
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"good": 0.10, "poor": 0.25, "unit": "", "label": "CLS"},
    "INTERACTION_TO_NEXT_PAINT": {"good": 200, "poor": 500, "unit": "ms", "label": "INP"},
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": {"good": 800, "poor": 1800, "unit": "ms", "label": "TTFB"},
    "FIRST_CONTENTFUL_PAINT_MS": {"good": 1800, "poor": 3000, "unit": "ms", "label": "FCP"},
}


@dataclass
class VitalsResult:
    strategy: str
    available: bool
    performance_score: Optional[float] = None
    field_data: Dict[str, Any] = field(default_factory=dict)
    lab_data: Dict[str, Any] = field(default_factory=dict)
    rating: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    source: str = "field" # "field" (CrUX real users) or "lab" (Lighthouse simulation) fallback


def _rate(value, key):
    t = THRESHOLDS[key]
    if value is None:
        return "unknown"
    if value <= t["good"]:
        return "good"
    if value <= t["poor"]:
        return "needs-improvement"
    return "poor"


def fetch_vitals(url: str, strategy: str = "mobile", api_key: Optional[str] = None,
                  timeout: int = 30) -> VitalsResult:
    """Fetch Core Web Vitals for one strategy ('mobile' or 'desktop').

    Prefers real Chrome UX Report field data (what Google actually uses for
    ranking/real users). Falls back to Lighthouse lab simulation if the
    origin/URL doesn't have enough CrUX traffic to report field data --
    common for smaller or newer sites.
    """
    api_key = api_key or os.environ.get("PSI_API_KEY")
    params = {"url": url, "strategy": strategy, "category": "PERFORMANCE"}
    if api_key:
        params["key"] = api_key
    try:
        r = requests.get(PSI_ENDPOINT, params=params, timeout=timeout)
        if r.status_code != 200:
            return VitalsResult(strategy=strategy, available=False,
                                 error=f"PageSpeed API returned HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
    except Exception as e:
        return VitalsResult(strategy=strategy, available=False, error=str(e))

    lab = {}
    try:
        lh = data["lighthouseResult"]
        lab_score = round(lh["categories"]["performance"]["score"] * 100, 1)
        audits = lh.get("audits", {})
        for key, aid in [("LCP", "largest-contentful-paint"), ("CLS", "cumulative-layout-shift"),
                          ("TTFB", "server-response-time"), ("FCP", "first-contentful-paint"),
                          ("TBT", "total-blocking-time"), ("SI", "speed-index")]:
            a = audits.get(aid)
            if a:
                lab[key] = {"value": a.get("numericValue"), "display": a.get("displayValue")}
    except Exception:
        lab_score = None

    field_data = {}
    source = "lab"
    try:
        loading_exp = data.get("loadingExperience") or data.get("originLoadingExperience")
        metrics = (loading_exp or {}).get("metrics", {})
        if metrics:
            source = "field"
            for key, meta in THRESHOLDS.items():
                m = metrics.get(key)
                if m:
                    field_data[meta["label"]] = {
                        "value": m.get("percentile"),
                        "category": m.get("category", "").lower().replace("_", "-"),
                    }
    except Exception:
        pass

    rating = {}
    ref = field_data if field_data else {
        "LCP": {"value": (lab.get("LCP") or {}).get("value")},
        "CLS": {"value": (lab.get("CLS") or {}).get("value")},
    }
    for label, key in [("LCP", "LARGEST_CONTENTFUL_PAINT_MS"), ("CLS", "CUMULATIVE_LAYOUT_SHIFT_SCORE")]:
        v = ref.get(label, {}).get("value")
        rating[label] = _rate(v, key)

    return VitalsResult(strategy=strategy, available=True, performance_score=lab_score,
                         field_data=field_data, lab_data=lab, rating=rating, source=source)


def fetch_both(url: str, api_key: Optional[str] = None, pause: float = 1.0) -> Dict[str, VitalsResult]:
    """Fetch mobile + desktop. A short pause avoids the unauthenticated rate limit."""
    mobile = fetch_vitals(url, "mobile", api_key)
    time.sleep(pause)
    desktop = fetch_vitals(url, "desktop", api_key)
    return {"mobile": mobile, "desktop": desktop}


def to_issues(results: Dict[str, VitalsResult]):
    """Convert VitalsResult objects into pro_scanner.ProIssue-compatible dicts.
    Imported lazily inside pro_scanner.py to avoid a circular import."""
    out = []
    for strategy, res in results.items():
        if not res.available:
            out.append(dict(category="performance", severity="info", location=f"PageSpeed API ({strategy})",
                             message=f"Could not fetch real Core Web Vitals for {strategy}: {res.error}",
                             impact="low", confidence=.5,
                             remediation="Re-run with network access to googleapis.com, or pass --psi-key."))
            continue
        src_label = "real Chrome-user field data" if res.source == "field" else "Lighthouse lab simulation (no field data yet -- likely low/new traffic)"
        if res.performance_score is not None and res.performance_score < 50:
            out.append(dict(category="performance", severity="error", location=f"Lighthouse ({strategy})",
                             message=f"Lighthouse performance score is {res.performance_score}/100 on {strategy} ({src_label}).",
                             impact="critical", confidence=.95,
                             remediation="Prioritize LCP (image/server) and TBT/INP (JS execution) fixes; this score directly affects Google's page-experience ranking signal.",
                             standard="Core Web Vitals / Google Lighthouse"))
        elif res.performance_score is not None and res.performance_score < 90:
            out.append(dict(category="performance", severity="warning", location=f"Lighthouse ({strategy})",
                             message=f"Lighthouse performance score is {res.performance_score}/100 on {strategy} ({src_label}).",
                             impact="high", confidence=.95,
                             remediation="Target 90+ for a 'good' Core Web Vitals classification in Search Console.",
                             standard="Core Web Vitals / Google Lighthouse"))
        for label in ("LCP", "CLS", "INP"):
            rating = res.rating.get(label)
            src = res.field_data.get(label) or res.lab_data.get(label)
            if not src:
                continue
            val = src.get("value")
            if rating == "poor":
                out.append(dict(category="performance", severity="error", location=f"{label} ({strategy})",
                                 message=f"{label} is in the 'poor' range on {strategy} ({src_label}): {val}.",
                                 impact="critical", confidence=.9,
                                 remediation=f"{label} directly gates the Core Web Vitals ranking assessment and correlates with checkout abandonment; treat as P0.",
                                 standard="Core Web Vitals"))
            elif rating == "needs-improvement":
                out.append(dict(category="performance", severity="warning", location=f"{label} ({strategy})",
                                 message=f"{label} needs improvement on {strategy} ({src_label}): {val}.",
                                 impact="high", confidence=.85,
                                 remediation=f"Improve {label} to reach the 'good' threshold.",
                                 standard="Core Web Vitals"))
    return out
