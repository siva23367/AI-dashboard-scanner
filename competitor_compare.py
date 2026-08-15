"""
Competitor Benchmark Mode
--------------------------
Runs the full Pro scan (core rule engine + accessibility/SEO/security/
performance/conversion + trust-signal audit) against your PDP AND a
handful of competitor PDPs, then produces a single side-by-side comparison:
scores per category, and a plain-English "where we lag / where we lead"
gap list. This is usually the single most persuasive artifact for a founder
or investor conversation -- "here is our page vs. the market leader's page,
scored the same way" lands harder than any absolute number.

Usage (as a library, called from pro_scanner.py's --competitors flag):
    from competitor_compare import run_comparison
    result = run_comparison(primary_url, competitor_urls)

Usage (standalone CLI):
    python competitor_compare.py https://mystore.com/p/1 \
        --vs https://competitor-a.com/p/1 https://competitor-b.com/p/9
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import scanner as core
import pro_scanner as pro
import pdf_export


def _scan_one(url: str, use_llm: bool = False, render: bool = False):
    core_report = core.scan_url(url, use_llm=use_llm, force_render=render, check_links=False)
    if core_report.skipped:
        return None, core_report.skip_reason
    soup, content, _ = core.fetch_and_extract(url, force_render=render)
    response, _ = pro.fetch_headers(url)
    report = pro.build_report(url, soup, content, response, core_report)
    return report, None


def run_comparison(primary_url: str, competitor_urls: List[str], use_llm: bool = False,
                    render: bool = False):
    entries = []
    for label, url in [("you", primary_url)] + [(f"competitor_{i+1}", u) for i, u in enumerate(competitor_urls)]:
        report, skip_reason = _scan_one(url, use_llm=use_llm, render=render)
        entries.append({"label": label, "url": url, "report": report, "skipped": skip_reason})

    categories = ["accessibility", "seo", "performance", "security", "conversion",
                  "overall_health_score"]
    table = []
    for e in entries:
        row = {"label": e["label"], "url": e["url"]}
        if e["report"]:
            row.update({c: e["report"].scores.get(c) for c in categories})
        else:
            row["error"] = e["skipped"]
        table.append(row)

    gaps = []
    you = next((e for e in entries if e["label"] == "you" and e["report"]), None)
    if you:
        for e in entries:
            if e is you or not e["report"]:
                continue
            for c in categories:
                yv, cv = you["report"].scores.get(c, 0), e["report"].scores.get(c, 0)
                if cv - yv >= 8:
                    gaps.append(f"{e['url']} scores {cv - yv:.0f} pts higher than you on {c.replace('_', ' ')} "
                                f"({cv:.0f} vs {yv:.0f}).")
                elif yv - cv >= 8:
                    gaps.append(f"You lead {e['url']} by {yv - cv:.0f} pts on {c.replace('_', ' ')} "
                                f"({yv:.0f} vs {cv:.0f}).")

    return {"generated_at": datetime.now(timezone.utc).isoformat(), "table": table,
            "gap_analysis": gaps, "raw": entries}


def html_comparison(result: dict) -> str:
    categories = ["overall_health_score", "accessibility", "seo", "performance",
                  "security", "conversion"]
    header = "".join(f"<th>{escape(c.replace('_', ' ').title())}</th>" for c in categories)

    def cell(v):
        if v is None:
            return "<td>-</td>"
        cls = "good" if v >= 80 else "warn" if v >= 60 else "bad"
        return f'<td class="{cls}">{v}</td>'

    rows = ""
    for row in result["table"]:
        if "error" in row:
            rows += f'<tr><td><b>{escape(row["label"])}</b><br><small>{escape(row["url"])}</small></td>' \
                    f'<td colspan="{len(categories)}">Skipped: {escape(str(row["error"]))}</td></tr>'
            continue
        rows += f'<tr><td><b>{escape(row["label"])}</b><br><small>{escape(row["url"])}</small></td>'
        rows += "".join(cell(row.get(c)) for c in categories)
        rows += "</tr>"

    gaps = "".join(f"<li>{escape(g)}</li>" for g in result["gap_analysis"]) or "<li>No 8+ point gaps detected.</li>"

    return f'''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Competitor Benchmark</title>
<style>body{{font-family:Inter,Arial,sans-serif;background:#f5f7fb;color:#172033;margin:0}}
.wrap{{max-width:1300px;margin:auto;padding:32px}}h1{{margin-bottom:4px}}.muted{{color:#687386}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden}}
td,th{{padding:12px;border-bottom:1px solid #edf0f5;text-align:left}}th{{background:#f8fafc}}
.good{{color:#16834a;font-weight:700}}.warn{{color:#b26a00;font-weight:700}}.bad{{color:#c53030;font-weight:700}}
section{{background:#fff;border:1px solid #e5e9f0;border-radius:14px;padding:22px;margin:18px 0}}</style>
</head><body><div class="wrap">
<h1>Competitor Benchmark</h1><div class="muted">Generated {escape(result["generated_at"])}</div>
<section><h2>Score Comparison</h2><table><tr><th>Site</th>{header}</tr>{rows}</table></section>
<section><h2>Gap Analysis</h2><ul>{gaps}</ul></section>
</div></body></html>'''


def main():
    p = argparse.ArgumentParser(description="Competitor benchmark comparison")
    p.add_argument("url", help="Your PDP URL")
    p.add_argument("--vs", nargs="+", required=True, help="Competitor PDP URLs")
    p.add_argument("--render", action="store_true")
    p.add_argument("--out", default=None)
    p.add_argument("--no-pdf", action="store_true", help="Skip generating the .pdf version of the comparison report")
    args = p.parse_args()
    result = run_comparison(args.url, args.vs, render=args.render)
    out = Path(args.out or f"competitor_benchmark_{urlparse(args.url).netloc.replace(':', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    out_json = out.with_suffix(".json")
    out_html = out.with_suffix(".html")
    out_pdf = out.with_suffix(".pdf")
    serializable = {**result, "raw": [
        {"label": e["label"], "url": e["url"], "skipped": e["skipped"],
         "report": asdict(e["report"]) if e["report"] else None} for e in result["raw"]
    ]}
    out_json.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    rendered_html = html_comparison(result)
    out_html.write_text(rendered_html, encoding="utf-8")
    print(f"JSON: {out_json}\nHTML: {out_html}")
    if not args.no_pdf:
        pdf_export.try_html_to_pdf(rendered_html, out_pdf, landscape=True, label="competitor benchmark")
    for g in result["gap_analysis"]:
        print(" -", g)


if __name__ == "__main__":
    main()
