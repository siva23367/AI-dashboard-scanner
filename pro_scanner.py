"""
Sriya Web Intelligence Scanner (Pro)
-------------------------------------------------
Builds on the existing PDP scanner and adds:
- Accessibility/WCAG 2.2 coverage
- Technical SEO + ecommerce structured-data audit
- Security-header posture
- Static performance/readiness audit
- Conversion-friction audit
- Unified 0-100 health scoring with severity/impact/confidence
- Executive HTML report with quick wins and prioritized roadmap
- Baseline/diff support for repeated scans

Important: this is a static/black-box audit. It does not claim to discover
runtime vulnerabilities, real user behavior, or actual conversion lift.
"""
from __future__ import annotations

import argparse, json, os, re, time, hashlib
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import scanner as core
import trust_signals
import web_vitals
import revenue_impact as revimp
import product_research
import pdf_export


@dataclass
class ProIssue:
    category: str
    severity: str
    location: str
    message: str
    impact: str = "medium"
    confidence: float = 0.9
    remediation: Optional[str] = None
    evidence: Optional[str] = None
    standard: Optional[str] = None
    signal_tag: Optional[str] = None
    count: int = 1

    def key(self):
        return (self.category, self.severity, self.location, self.message)


@dataclass
class ProReport:
    url: str
    scanned_at: str
    page_type: str = "product"
    scores: Dict[str, float] = field(default_factory=dict)
    issues: List[ProIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    executive_summary: List[str] = field(default_factory=list)
    quick_wins: List[str] = field(default_factory=list)
    roadmap: List[str] = field(default_factory=list)
    baseline_delta: Optional[Dict[str, Any]] = None
    revenue_impact: Optional[Dict[str, Any]] = None
    web_vitals: Optional[Dict[str, Any]] = None
    product_research: Optional[Dict[str, Any]] = None

    def summary(self):
        out = {"error": 0, "warning": 0, "info": 0}
        for i in self.issues:
            out[i.severity] = out.get(i.severity, 0) + i.count
        return out


def issue(category, severity, location, message, *, impact="medium", confidence=.9,
          remediation=None, evidence=None, standard=None, signal_tag=None, count=1):
    return ProIssue(category, severity, location, message, impact, confidence,
                    remediation, evidence, standard, signal_tag, count)


def _text(soup, selectors):
    for sel in selectors:
        x = soup.select_one(sel)
        if x:
            t = x.get_text(" ", strip=True)
            if t:
                return t
    return ""


def _meta(soup, name=None, prop=None):
    attrs = {"name": name} if name else {"property": prop}
    x = soup.find("meta", attrs=attrs)
    return (x.get("content") or "").strip() if x else ""


def _same_origin(url, target):
    a, b = urlparse(url), urlparse(urljoin(url, target))
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def fetch_headers(url, timeout=15):
    try:
        r = requests.get(url, headers=core.DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
        return r, None
    except Exception as e:
        return None, str(e)


def parse_jsonld(soup):
    blocks=[]
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data=json.loads(s.string or s.get_text() or "{}")
            blocks.append(data)
        except Exception:
            continue
    flat=[]
    def walk(x):
        if isinstance(x, dict):
            flat.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    for b in blocks: walk(b)
    return flat


def schema_audit(soup, url):
    issues=[]; nodes=parse_jsonld(soup)
    products=[n for n in nodes if n.get("@type") == "Product" or (isinstance(n.get("@type"),list) and "Product" in n.get("@type",[]))]
    if not products:
        issues.append(issue("seo", "warning", "JSON-LD", "Product structured data is missing.", impact="high", confidence=.98,
            remediation="Add valid Product + Offer JSON-LD using the canonical product URL, price, currency, availability and brand.",
            standard="Schema.org Product / Google Product structured data", signal_tag="product discoverability"))
        return issues, {"product_schema": False}
    p=products[0]
    required=[("name","Product name"),("image","Product image"),("description","Product description"),("brand","Brand"),("offers","Offer")]
    for k,label in required:
        if not p.get(k):
            issues.append(issue("seo","warning",f"Product.{k}",f"Product schema is missing {label} ({k}).",impact="high" if k in ("name","offers") else "medium",confidence=.97,
                remediation=f"Populate Product schema field: {k}.",standard="Schema.org Product",signal_tag="product data completeness"))
    offers=p.get("offers")
    if offers:
        if isinstance(offers,dict):
            if not offers.get("price"): issues.append(issue("seo","warning","Product.offers.price","Offer has no price.",impact="high",standard="Google merchant listings",signal_tag="price clarity"))
            if not offers.get("priceCurrency"): issues.append(issue("seo","warning","Product.offers.priceCurrency","Offer has no priceCurrency.",impact="medium",standard="Google merchant listings"))
            if not offers.get("availability"): issues.append(issue("seo","info","Product.offers.availability","Offer has no availability value.",impact="medium",standard="Google merchant listings"))
        elif isinstance(offers,list) and not offers:
            issues.append(issue("seo","warning","Product.offers","Offers array is empty.",impact="high"))
    if not p.get("aggregateRating") and not p.get("review"):
        issues.append(issue("seo","info","Product reviews schema","No review/aggregateRating data detected in Product schema.",impact="medium",standard="Google Product structured data",signal_tag="trust"))
    return issues,{"product_schema":True,"schema_keys":sorted(p.keys())}


def product_identity(soup, url):
    """Best-effort product name/brand for --research, reusing whatever
    schema.org Product data schema_audit() already parses. Falls back to
    <title> if there's no structured data (same page still gets researched,
    just with a noisier query)."""
    nodes = parse_jsonld(soup)
    products = [n for n in nodes if n.get("@type") == "Product" or
                (isinstance(n.get("@type"), list) and "Product" in n.get("@type", []))]
    if products:
        p = products[0]
        name = p.get("name")
        brand = p.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        return (name or "").strip() or None, (brand or "").strip() if brand else None
    title = soup.title.get_text(strip=True) if soup.title else None
    return title, None


def accessibility_audit(soup):
    out=[]
    # WCAG 2.2 additions / practical checks
    lang=soup.html.get("lang") if soup.html else None
    if not lang:
        out.append(issue("accessibility","warning","<html>","Document language is missing.",impact="medium",standard="WCAG 3.1.1 Language of Page",remediation="Set <html lang=\"en\"> (or the actual page language)."))
    for i,img in enumerate(soup.find_all("img"),1):
        src=img.get("src","")
        if core._is_tracking_pixel(img): continue
        if img.get("alt") is None:
            out.append(issue("accessibility","error",f"img #{i}","Image has no alt attribute.",impact="high",standard="WCAG 1.1.1 Non-text Content",remediation="Add concise descriptive alt text; use alt=\"\" only for decorative images."))
        if img.get("width") is None or img.get("height") is None:
            out.append(issue("performance","info",f"img #{i}","Image dimensions are not declared.",impact="medium",remediation="Declare width/height or aspect-ratio to reduce layout shift."))
    for i,el in enumerate(soup.find_all(["button","a","input","select","textarea"]),1):
        if el.name=="a" and not el.get("href"):
            continue
        if el.name in ("input","select","textarea"):
            has_label = bool(el.get("aria-label") or el.get("aria-labelledby") or el.get("id") and soup.find("label",attrs={"for":el.get("id")}))
            if not has_label:
                out.append(issue("accessibility","error",f"<{el.name}> #{i}","Form control has no accessible label.",impact="high",standard="WCAG 1.3.1 / 3.3.2",remediation="Associate a <label> or provide aria-label/aria-labelledby."))
    # WCAG 2.2 target size heuristic
    for i,el in enumerate(soup.find_all(["button","a"]),1):
        style=(el.get("style") or "").lower()
        if re.search(r'(width|height)\s*:\s*(1[0-9]|[0-9])px',style):
            out.append(issue("accessibility","warning",f"interactive #{i}","Inline style suggests an interactive target may be smaller than the WCAG 2.2 target-size minimum.",impact="medium",standard="WCAG 2.5.8 Target Size (Minimum)",remediation="Ensure touch targets have at least 24×24 CSS px or adequate spacing."))
    # heading structure
    hs=soup.find_all(re.compile(r"^h[1-6]$")); levels=[int(x.name[1]) for x in hs]
    if levels and levels[0] != 1:
        out.append(issue("accessibility","warning","heading structure","First heading is not h1.",impact="medium",standard="WCAG 1.3.1",remediation="Use a single logical page heading starting at h1."))
    for a,b in zip(levels,levels[1:]):
        if b>a+1:
            out.append(issue("accessibility","warning",f"h{a}->h{b}","Heading hierarchy skips a level.",impact="medium",standard="WCAG 1.3.1",remediation="Use sequential heading levels to preserve document structure."))
    return out


def seo_audit(soup,url):
    out=[]
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    desc=_meta(soup,name="description")
    canonical=soup.find("link",rel=lambda x:x and "canonical" in x)
    viewport=_meta(soup,name="viewport")
    robots=_meta(soup,name="robots")
    og_title=_meta(soup,prop="og:title"); og_image=_meta(soup,prop="og:image")
    if not title: out.append(issue("seo","error","<title>","Page title is missing.",impact="high",standard="SEO",remediation="Add a unique product title."))
    elif len(title)<30 or len(title)>65: out.append(issue("seo","warning","<title>",f"Title length is {len(title)} characters.",impact="medium",remediation="Use a concise, unique title focused on product intent."))
    if not desc: out.append(issue("seo","warning","meta description","Meta description is missing.",impact="medium",remediation="Add a unique product-focused meta description."))
    elif len(desc)>160: out.append(issue("seo","info","meta description",f"Meta description is {len(desc)} characters and may be truncated.",impact="low",remediation="Shorten the description while preserving the main product value proposition."))
    if not canonical: out.append(issue("seo","warning","canonical","Canonical link is missing.",impact="medium",remediation="Add a self-referencing canonical URL for the primary product URL."))
    if not viewport: out.append(issue("seo","warning","viewport","Mobile viewport meta tag is missing.",impact="high",remediation="Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">."))
    if robots and "noindex" in robots.lower(): out.append(issue("seo","error","robots","Page is marked noindex.",impact="high",remediation="Remove noindex if this product should be discoverable."))
    if not og_title or not og_image: out.append(issue("seo","info","Open Graph","Open Graph title/image metadata is incomplete.",impact="low",remediation="Add og:title and og:image for richer social sharing."))
    # hreflang integrity
    links=soup.find_all("link",rel=lambda x:x and "alternate" in x)
    hreflangs=[x.get("hreflang") for x in links if x.get("hreflang")]
    if hreflangs and "x-default" not in hreflangs: out.append(issue("seo","info","hreflang","hreflang set exists but has no x-default alternate.",impact="low",remediation="Consider x-default for international routing."))
    return out,{"title_length":len(title),"meta_description_length":len(desc),"has_canonical":bool(canonical),"has_viewport":bool(viewport),"noindex":bool(robots and "noindex" in robots.lower()),"has_og":bool(og_title and og_image)}


def security_audit(response):
    out=[]
    if response is None:
        return [issue("security","info","HTTP response","Security headers could not be inspected.",impact="medium",confidence=.6,remediation="Run the scanner against a reachable HTTPS response.")]
    h={k.lower():v for k,v in response.headers.items()}
    if response.url.startswith("https://"):
        checks=[
            ("strict-transport-security","HSTS","warning","high","Deploy HSTS with an appropriate max-age and consider includeSubDomains after validation."),
            ("content-security-policy","CSP","warning","high","Deploy a restrictive Content-Security-Policy and tune it for the application."),
            ("x-content-type-options","X-Content-Type-Options","warning","medium","Set X-Content-Type-Options: nosniff."),
            ("referrer-policy","Referrer-Policy","info","low","Set an explicit privacy-preserving Referrer-Policy."),
            ("permissions-policy","Permissions-Policy","info","low","Restrict unnecessary browser capabilities."),
        ]
        for key,label,sev,impact,fix in checks:
            if key not in h:
                out.append(issue("security",sev,label,f"{label} header is missing.",impact=impact,remediation=fix,confidence=.98))
        if "x-frame-options" not in h and "frame-ancestors" not in h.get("content-security-policy",""):
            out.append(issue("security","warning","clickjacking","No X-Frame-Options or CSP frame-ancestors directive detected.",impact="high",remediation="Block untrusted framing using CSP frame-ancestors or X-Frame-Options."))
    else:
        out.append(issue("security","error","transport","Page is not served over HTTPS.",impact="critical",remediation="Serve the product page over HTTPS and redirect HTTP to HTTPS."))
    return out


def performance_audit(soup):
    out=[]
    imgs=soup.find_all("img"); scripts=soup.find_all("script"); links=soup.find_all("link")
    lazy=sum(1 for x in imgs if (x.get("loading") or "").lower()=="lazy")
    modern=0
    for img in imgs:
        src=img.get("src","").lower()
        if any(src.split("?")[0].endswith(ext) for ext in (".webp",".avif")): modern+=1
    if len(imgs)>=8 and lazy/max(1,len(imgs))<.5:
        out.append(issue("performance","warning","images",f"Only {lazy}/{len(imgs)} images explicitly use lazy loading.",impact="medium",remediation="Lazy-load below-the-fold images; keep the hero image eager/high priority."))
    if imgs and modern/max(1,len(imgs))<.5:
        out.append(issue("performance","info","image formats",f"Only {modern}/{len(imgs)} image URLs appear to use WebP/AVIF.",impact="medium",remediation="Prefer responsive WebP/AVIF sources with fallbacks."))
    if len(scripts)>30:
        out.append(issue("performance","warning","scripts",f"Page contains {len(scripts)} script tags.",impact="medium",remediation="Audit third-party scripts and defer non-critical JavaScript."))
    render_blocking=[s for s in scripts if s.get("src") and not s.has_attr("async") and not s.has_attr("defer") and not s.get("type")]
    if len(render_blocking)>8:
        out.append(issue("performance","warning","render-blocking scripts",f"{len(render_blocking)} external scripts appear render-blocking.",impact="high",remediation="Defer/async non-critical scripts and inline only critical bootstrapping."))
    if not any(x.get("rel") and "preconnect" in x.get("rel") for x in links):
        out.append(issue("performance","info","preconnect","No preconnect hints detected.",impact="low",remediation="Add preconnect only for critical third-party origins."))
    return out,{"image_count":len(imgs),"lazy_images":lazy,"modern_image_urls":modern,"script_count":len(scripts),"render_blocking_scripts":len(render_blocking)}


def ecommerce_audit(soup, content):
    out=[]
    body=soup.get_text(" ",strip=True).lower()
    cta=bool(re.search(r"add to (cart|bag)|buy now|purchase",body))
    price=bool(re.search(r"(?:₹|rs\.?|\$|€|£)\s*[0-9]|[0-9][0-9,.]*\s*(?:inr|usd|eur|gbp)",body,re.I))
    reviews=bool(re.search(r"reviews?|ratings?|stars?",body))
    delivery=bool(re.search(r"delivery|deliver by|shipping",body))
    returns=bool(re.search(r"return|refund",body))
    payment=bool(re.search(r"upi|visa|mastercard|emi|cash on delivery|payment",body))
    checks=[
        (cta,"conversion","warning","high","Primary purchase CTA is not detectable.","Expose a clear keyboard-accessible Add to Cart/Buy Now control.","CTA"),
        (price,"conversion","warning","high","Price is not detectable in visible page content.","Show current price, currency and offer state near the primary CTA.","price clarity"),
        (reviews,"conversion","info","medium","Review/rating trust signal is not detectable.","Surface review count and rating near the product decision area.","trust"),
        (delivery,"conversion","info","medium","Delivery/shipping information is not detectable.","Expose delivery estimate and shipping cost before checkout.","delivery confidence"),
        (returns,"conversion","info","medium","Return/refund information is not detectable.","Make return policy visible near the purchase decision.","trust"),
        (payment,"conversion","info","low","Payment-method reassurance is not detectable.","Show supported payment methods/EMI/COD where relevant.","checkout confidence"),
    ]
    for ok,cat,sev,imp,msg,fix,sig in checks:
        if not ok: out.append(issue(cat,sev,"product decision area",msg,impact=imp,remediation=fix,signal_tag=sig))
    return out,{"cta_detected":cta,"price_detected":price,"reviews_detected":reviews,"delivery_detected":delivery,"returns_detected":returns,"payment_detected":payment}


def convert_core_issues(core_issues):
    out=[]
    sevmap={"error":"error","warning":"warning","info":"info"}
    for i in core_issues:
        cat="accessibility" if i.message.lower().find("screen reader")>=0 or i.location.startswith(("<img>","<h1>","<select>","<input>","<table>")) else "semantic"
        out.append(issue(cat,sevmap.get(i.severity,i.severity),i.location,i.message,impact="high" if i.severity=="error" else "medium",confidence=.9,remediation=i.suggestion,evidence=i.snippet,count=i.count))
    return out


def weighted_score(issues, category):
    penalty={"critical":24,"high":10,"medium":4,"low":1}
    # confidence reduces the penalty of uncertain heuristic findings
    p=sum(penalty.get(i.impact,4)*max(.25,min(1,i.confidence))*i.count for i in issues if i.category==category)
    return round(max(0,min(100,100-p)),1)


def build_report(url,soup,content,response,core_report,vitals_result=None):
    issues=[]
    issues += convert_core_issues(core_report.issues)
    x,metrics_schema=schema_audit(soup,url); issues+=x
    x,metrics_seo=seo_audit(soup,url); issues+=x
    issues+=accessibility_audit(soup)
    x,metrics_perf=performance_audit(soup); issues+=x
    x,metrics_ecom=ecommerce_audit(soup,content); issues+=x
    x,metrics_trust=trust_signals.audit(soup,content); issues+=[issue(**d) for d in x]
    issues+=security_audit(response)
    vitals_metrics=None
    if vitals_result:
        issues += [issue(**d) for d in web_vitals.to_issues(vitals_result)]
        vitals_metrics = {
            strat: {
                "available": res.available,
                "performance_score": res.performance_score,
                "source": res.source,
                "field_data": res.field_data,
                "rating": res.rating,
                "error": res.error,
            } for strat, res in vitals_result.items()
        }
    # de-dupe by semantic fingerprint, preserving highest severity/impact
    merged={}; order=[]
    rank={"info":0,"warning":1,"error":2}; impact_rank={"low":0,"medium":1,"high":2,"critical":3}
    for i in issues:
        k=(i.category,i.location,i.message)
        if k not in merged:
            merged[k]=i; order.append(k)
        else:
            old=merged[k]; old.count+=i.count
            if rank[i.severity]>rank[old.severity]: old.severity=i.severity
            if impact_rank[i.impact]>impact_rank[old.impact]: old.impact=i.impact
            old.confidence=max(old.confidence,i.confidence)
    issues=[merged[k] for k in order]
    categories=["accessibility","seo","performance","security","conversion"]
    scores={c:weighted_score(issues,c) for c in categories}
    scores["overall_health_score"]=round(sum(scores.values())/len(categories),1)
    metrics={**metrics_schema,**metrics_seo,**metrics_perf,**metrics_ecom,**metrics_trust}
    summary=[]
    top=sorted(issues,key=lambda i:( {"critical":3,"high":2,"medium":1,"low":0}.get(i.impact,1), {"error":2,"warning":1,"info":0}.get(i.severity,0), i.count),reverse=True)
    for i in top[:5]: summary.append(f"{i.message} ({i.impact} impact)")
    quick=[]
    for i in top:
        if i.impact in ("critical","high") and i.remediation and len(quick)<5:
            quick.append(i.remediation)
    roadmap=[
        "P0: Fix critical/high-impact security, CTA, price and accessibility blockers.",
        "P1: Complete Product/Offer structured data and technical SEO metadata.",
        "P2: Reduce third-party/render-blocking assets and optimize images for Core Web Vitals.",
    ]
    return ProReport(url=url,scanned_at=datetime.now(timezone.utc).isoformat(),scores=scores,issues=issues,metrics=metrics,executive_summary=summary,quick_wins=quick,roadmap=roadmap,web_vitals=vitals_metrics)


def html_report(r:ProReport):
    def score_class(v): return "good" if v>=80 else "warn" if v>=60 else "bad"
    cards="".join(f'<div class="card"><div class="label">{escape(k.replace("_"," ").title())}</div><div class="score {score_class(v)}">{v}</div></div>' for k,v in r.scores.items())
    rows="".join(f'<tr><td>{escape(i.category)}</td><td>{escape(i.severity)}</td><td>{escape(i.impact)}</td><td>{escape(i.location)}</td><td><b>{escape(i.message)}</b><br><small>{escape(i.remediation or "")}</small></td><td>{i.count}</td></tr>' for i in sorted(r.issues,key=lambda x:(-{"critical":3,"high":2,"medium":1,"low":0}.get(x.impact,0),-{"error":2,"warning":1,"info":0}.get(x.severity,0)))[:100])
    metrics="".join(f'<tr><td>{escape(str(k))}</td><td>{escape(str(v))}</td></tr>' for k,v in r.metrics.items())
    summary="".join(f'<li>{escape(x)}</li>' for x in r.executive_summary)
    quick="".join(f'<li>{escape(x)}</li>' for x in r.quick_wins)
    roadmap="".join(f'<li>{escape(x)}</li>' for x in r.roadmap)

    revenue_section = ""
    if r.revenue_impact:
        ri = r.revenue_impact
        bullets = "".join(f"<li>{escape(x)}</li>" for x in ri.get("narrative", []))
        revenue_section = f'''<section><h2>💰 Estimated Revenue Impact</h2>
<div class="hero-number">${ri["estimate"]["estimated_monthly_revenue_at_risk"]:,.0f}<span class="hero-sub">/mo directional opportunity</span></div>
<ul>{bullets}</ul>
<p class="muted"><small>{escape(ri["estimate"]["disclaimer"])}</small></p></section>'''

    vitals_section = ""
    if r.web_vitals:
        rows_v = ""
        for strat, v in r.web_vitals.items():
            if not v.get("available"):
                rows_v += f'<tr><td>{escape(strat)}</td><td colspan="3">Unavailable: {escape(str(v.get("error")))}</td></tr>'
                continue
            fd = v.get("field_data") or {}
            lcp = fd.get("LCP", {}); cls_ = fd.get("CLS", {}); inp = fd.get("INP", {})
            rows_v += (f'<tr><td>{escape(strat)}</td><td>{v.get("performance_score")}</td>'
                       f'<td>{escape(v.get("source",""))}</td>'
                       f'<td>LCP:{lcp.get("category","-")} CLS:{cls_.get("category","-")} INP:{inp.get("category","-")}</td></tr>')
        vitals_section = f'''<section><h2>🚦 Real Core Web Vitals (Google PageSpeed Insights)</h2>
<p class="muted">Real Chrome-user / Lighthouse data, not HTML heuristics.</p>
<table><tr><th>Strategy</th><th>Lighthouse Score</th><th>Data Source</th><th>Field Ratings</th></tr>{rows_v}</table></section>'''

    research_section = product_research.html_section_from_dict(r.product_research) if r.product_research else ""

    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sriya Web Intelligence Audit</title>
<style>body{{font-family:Inter,Arial,sans-serif;background:#f5f7fb;color:#172033;margin:0}}.wrap{{max-width:1250px;margin:auto;padding:32px}}h1{{margin-bottom:4px}}.muted{{color:#687386}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}.card{{background:#fff;border:1px solid #e5e9f0;border-radius:14px;padding:18px}}.label{{text-transform:capitalize;color:#687386;font-size:13px}}.score{{font-size:34px;font-weight:800;margin-top:6px}}.good{{color:#16834a}}.warn{{color:#b26a00}}.bad{{color:#c53030}}section{{background:#fff;border:1px solid #e5e9f0;border-radius:14px;padding:22px;margin:18px 0}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #edf0f5;text-align:left;vertical-align:top}}th{{background:#f8fafc}}small{{color:#687386}}.pill{{display:inline-block;padding:4px 8px;border-radius:999px;background:#eef3ff}}.hero-number{{font-size:48px;font-weight:800;color:#16834a}}.hero-sub{{font-size:16px;font-weight:500;color:#687386;margin-left:8px}}</style></head><body><div class="wrap">
<h1>Website Intelligence Audit</h1><div class="muted">{escape(r.url)} · {escape(r.scanned_at)}</div><div class="grid">{cards}</div>
{revenue_section}
<section><h2>Founder / Executive Summary</h2><ul>{summary}</ul></section>
<section><h2>Quick Wins</h2><ol>{quick}</ol></section>
{vitals_section}
{research_section}
<section><h2>Prioritized Roadmap</h2><ol>{roadmap}</ol></section>
<section><h2>Metrics & Evidence</h2><table><tr><th>Metric</th><th>Value</th></tr>{metrics}</table></section>
<section><h2>Top Findings</h2><table><tr><th>Category</th><th>Severity</th><th>Impact</th><th>Location</th><th>Finding / Fix</th><th>Count</th></tr>{rows}</table></section>
</div></body></html>'''


def main():
    p=argparse.ArgumentParser(description="Sriya Web Intelligence Scanner")
    p.add_argument("url",nargs="?",help="PDP URL")
    p.add_argument("--no-llm",action="store_true")
    p.add_argument("--render",action="store_true")
    p.add_argument("--out",default=None)
    p.add_argument("--baseline",default=None,help="Previous pro JSON report for score delta")
    p.add_argument("--real-vitals",action="store_true",help="Fetch real Core Web Vitals from Google PageSpeed Insights (network call to googleapis.com)")
    p.add_argument("--psi-key",default=None,help="Optional PageSpeed Insights API key (else PSI_API_KEY env var / unauthenticated quota)")
    p.add_argument("--monthly-visitors",type=int,default=None,help="Estimated monthly visitors/traffic, enables the Revenue Impact section")
    p.add_argument("--aov",type=float,default=None,help="Average order value, enables the Revenue Impact section")
    p.add_argument("--conversion-rate",type=float,default=None,help="Current conversion rate as a fraction e.g. 0.025 for 2.5%% (defaults to 2.5%% industry mid-point)")
    p.add_argument("--currency",default="$",help="Currency symbol for the Revenue Impact section")
    p.add_argument("--competitors",nargs="+",default=None,help="One or more competitor PDP URLs to benchmark against")
    p.add_argument("--research",action="store_true",help="Live web search for references/mentions of this product (reviews, other listings, forum/video mentions) -- separate from the single-page audit above")
    p.add_argument("--research-terms",default=None,help="Extra search terms to append to the product research query, e.g. 'review' or a model number")
    p.add_argument("--research-results",type=int,default=8,help="Max search results to pull for --research (default 8)")
    p.add_argument("--search-key",default=None,help="Optional Bing Web Search API key for --research (else BING_SEARCH_KEY env var / free DuckDuckGo HTML fallback)")
    p.add_argument("--no-pdf",action="store_true",help="Skip generating the .pdf version of the report (PDF is generated by default via headless Chromium)")
    args=p.parse_args(); url=args.url or input("Enter website URL to scan: ").strip()
    print("[pro] Fetching page and running core PDP scanner...")
    core_report=core.scan_url(url,use_llm=not args.no_llm,force_render=args.render,check_links=False)
    if core_report.skipped:
        print(f"[pro] Skipped: {core_report.skip_reason}"); return 2
    soup,content,used_render=core.fetch_and_extract(url,force_render=args.render)
    response,err=fetch_headers(url)
    vitals_result=None
    if args.real_vitals:
        print("[pro] Fetching real Core Web Vitals from PageSpeed Insights...")
        vitals_result=web_vitals.fetch_both(url,api_key=args.psi_key)
    r=build_report(url,soup,content,response,core_report,vitals_result=vitals_result)
    if args.monthly_visitors and args.aov:
        est=revimp.estimate(r.scores,monthly_visitors=args.monthly_visitors,aov=args.aov,conversion_rate=args.conversion_rate)
        r.revenue_impact={"estimate":asdict(est),"narrative":revimp.narrative(est,currency=args.currency)}
    if args.research:
        pname, pbrand = product_identity(soup, url)
        if pname:
            print(f"[pro] Researching web references for: {pbrand + ' ' if pbrand else ''}{pname} ...")
            rr = product_research.research_product(pname, brand=pbrand, num_results=args.research_results,
                                                     api_key=args.search_key, extra_terms=args.research_terms)
            r.product_research = product_research.to_dict(rr)
            print(f"[pro] Research: {rr.reference_summary[0] if rr.reference_summary else 'no summary'}")
        else:
            print("[pro] --research skipped: could not determine a product name/title from this page.")
    if args.competitors:
        print(f"[pro] Running competitor benchmark against {len(args.competitors)} site(s)...")
        import competitor_compare as cc
        comp=cc.run_comparison(url,args.competitors,use_llm=not args.no_llm,render=args.render)
        comp_out=Path((args.out or f"pro_report_{urlparse(url).netloc.replace(':','_')}")).with_name(
            (Path(args.out).stem if args.out else f"pro_report_{urlparse(url).netloc.replace(':','_')}")+"_competitor_benchmark")
        Path(str(comp_out)+".json").write_text(json.dumps({**comp,"raw":[{"label":e["label"],"url":e["url"],"skipped":e["skipped"],"report":(asdict(e["report"]) if e["report"] else None)} for e in comp["raw"]]},indent=2,ensure_ascii=False,default=str),encoding="utf-8")
        comp_html=cc.html_comparison(comp)
        Path(str(comp_out)+".html").write_text(comp_html,encoding="utf-8")
        print(f"[pro] Competitor benchmark: {comp_out}.html")
        if not args.no_pdf:
            pdf_export.try_html_to_pdf(comp_html,str(comp_out)+".pdf",landscape=True,label="competitor benchmark")
        for g in comp["gap_analysis"]: print(" -",g)
    if args.baseline and Path(args.baseline).exists():
        try:
            old=json.loads(Path(args.baseline).read_text())
            old_scores=old.get("scores",{})
            r.baseline_delta={k:round(r.scores.get(k,0)-old_scores.get(k,0),1) for k in r.scores if k in old_scores}
        except Exception as e: print(f"[pro] baseline ignored: {e}")
    out=Path(args.out or f"pro_report_{urlparse(url).netloc.replace(':','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    if out.suffix.lower() not in (".json",".html"): out_json=out.with_suffix('.json'); out_html=out.with_suffix('.html')
    else: out_json=out.with_suffix('.json'); out_html=out.with_suffix('.html')
    payload=asdict(r); out_json.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
    rendered_html=html_report(r); out_html.write_text(rendered_html,encoding='utf-8')
    out_pdf=out.with_suffix('.pdf')
    if not args.no_pdf:
        pdf_export.try_html_to_pdf(rendered_html,out_pdf,label="scan report")
    print("\n=== SRIYA WEB INTELLIGENCE ===")
    print(f"Overall Health: {r.scores['overall_health_score']}/100")
    for k,v in r.scores.items(): print(f"{k:24} {v:5.1f}")
    print(f"Issues: {r.summary()}")
    if r.revenue_impact:
        print(f"Estimated Revenue Opportunity: {args.currency}{r.revenue_impact['estimate']['estimated_monthly_revenue_at_risk']:,.0f}/mo "
              f"({args.currency}{r.revenue_impact['estimate']['estimated_annual_revenue_at_risk']:,.0f}/yr, directional)")
    print(f"JSON: {out_json}")
    print(f"HTML: {out_html}")
    if not args.no_pdf and out_pdf.exists():
        print(f"PDF:  {out_pdf}")
    return 0

if __name__=="__main__": raise SystemExit(main())