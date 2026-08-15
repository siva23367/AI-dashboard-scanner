"""
webapp.py -- minimal login-gated web front end for the Sriya Web Intelligence
Scanner and the PDF dashboard-ingestion pipeline.

Flow
----
  /login      -> single-user login (credentials from .env)
  /           -> home page: choose one of Dashboard / PDF / Website Link
  /website    -> enter a PDP URL -> runs the SAME pipeline as pro_scanner.py
                 (semantic + spelling issues from scanner.py's core engine,
                 plus SEO/accessibility/security/performance/conversion from
                 pro_scanner.py) -> saves + shows the report
  /pdf        -> upload a dashboard PDF/image -> runs dashboard_ingest.py's
                 text/OCR pipeline -> saves + shows a dashboard summary
  /dashboard  -> lists every report generated so far, newest first

Nothing here re-implements scoring or extraction logic -- every route just
calls into pro_scanner.py / scanner.py / dashboard_ingest.py / pdf_export.py,
the same functions the CLI tools use, so the web UI and CLI always produce
identical output.
"""
from __future__ import annotations

import functools
import json
import os
import secrets
import traceback
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask, request, redirect, url_for, render_template_string,
    session, send_from_directory, flash, jsonify, send_file,
)
from werkzeug.utils import secure_filename

import scanner as core
import pro_scanner as pro
import dashboard_ingest as ingest
import dashboard_search as dsearch
import pdf_export
import product_research

APP_ROOT = Path(__file__).parent
REPORTS_DIR = APP_ROOT / "reports"
UPLOADS_DIR = APP_ROOT / "uploads"
REPORTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
INDEX_PATH = REPORTS_DIR / "index.json"
ALLOWED_UPLOAD_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

app = Flask(__name__)
app.secret_key = os.environ.get("WEBAPP_SECRET_KEY") or secrets.token_hex(32)

# Single-user login. Set WEBAPP_USERNAME / WEBAPP_PASSWORD in .env for real
# use. Falls back to admin/admin for local testing only -- change this
# before running the app anywhere reachable outside localhost.
WEBAPP_USERNAME = os.environ.get("WEBAPP_USERNAME", "admin")
WEBAPP_PASSWORD = os.environ.get("WEBAPP_PASSWORD", "admin")


# ---------------------------------------------------------------- auth ----

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def api_login_required(view):
    """Same session check as login_required, but for the JSON API: returns a
    401 JSON body instead of redirecting to the HTML login page, so the React
    frontend can react to it (e.g. show the login screen) instead of
    following a redirect into an HTML page."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify(ok=False, error="Not logged in."), 401
        return view(*args, **kwargs)
    return wrapped


# ----------------------------------------------------------- report log ---

def _load_index():
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_index(entries):
    INDEX_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _add_report(entry: dict):
    entries = _load_index()
    entries.insert(0, entry)
    _save_index(entries)


def _new_report_dir():
    rid = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    d = REPORTS_DIR / rid
    d.mkdir(parents=True, exist_ok=True)
    return rid, d


# --------------------------------------------------------------- style ----

BASE_CSS = """
:root{
  --navy-900:#0b1330; --navy-800:#101a3f; --blue-600:#2b5fff; --blue-500:#4f7bff;
  --ink:#172033; --muted:#687386; --border:#e5e9f0; --bg:#f5f7fb;
  --good:#16834a; --good-bg:#e9f8ef; --warn:#b26a00; --warn-bg:#fff6e5; --bad:#c53030; --bad-bg:#fdeceb;
  --radius:16px;
}
*{box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink);margin:0;-webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:auto;padding:0 24px 48px}
.wrap.wide{max-width:1250px}
h1{margin:0 0 4px;letter-spacing:-.01em}
h2{letter-spacing:-.005em}
.muted{color:var(--muted)}
a{color:var(--blue-600);text-decoration:none}
a:hover{text-decoration:underline}

/* ---- hero banner, same visual language as the executive PDF dashboards ---- */
.hero{
  background:radial-gradient(120% 160% at 0% 0%,#1b2a63 0%,var(--navy-900) 55%,#070c1f 100%);
  color:#fff;border-radius:0 0 22px 22px;padding:34px 28px 30px;margin-bottom:28px;
  box-shadow:0 10px 30px rgba(11,19,48,.25);
}
.hero-inner{max-width:1250px;margin:auto;display:flex;justify-content:space-between;align-items:flex-start;gap:20px;flex-wrap:wrap}
.hero-badge{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);
  color:#cfe0ff;font-size:12px;font-weight:600;padding:5px 12px;border-radius:999px;margin-bottom:12px}
.hero h1{color:#fff;font-size:26px}
.hero p{color:#aab6d6;margin:6px 0 0;max-width:640px;font-size:14px}
.hero-right{display:flex;flex-direction:column;align-items:flex-end;gap:8px}
.hero-pill{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.18);color:#dfe7ff;font-size:12.5px;padding:6px 12px;border-radius:999px}
.hero-logout{color:#cfe0ff;font-size:13px}
.hero-logout:hover{color:#fff}

/* ---- generic cards / kpis ---- */
.card{background:#fff;border:1px solid var(--border);border-radius:var(--radius);padding:22px;margin:16px 0;box-shadow:0 1px 2px rgba(16,26,63,.03)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:0 0 22px}
.kpi{background:#fff;border:1px solid var(--border);border-radius:14px;padding:16px 18px;border-top:3px solid var(--blue-500)}
.kpi .k-label{color:var(--muted);font-size:12.5px;display:flex;align-items:center;gap:6px}
.kpi .k-value{font-size:26px;font-weight:800;margin-top:4px;letter-spacing:-.02em}

/* ---- option tiles on the home page ---- */
.options{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-top:4px}
.option{background:#fff;border:1px solid var(--border);border-radius:var(--radius);padding:26px 22px;text-align:left;cursor:pointer;transition:.15s;display:block}
.option:hover{border-color:var(--blue-600);box-shadow:0 8px 20px rgba(43,95,255,.14);transform:translateY(-2px);text-decoration:none}
.option .emoji{font-size:30px;width:52px;height:52px;display:flex;align-items:center;justify-content:center;background:#eef3ff;border-radius:12px;margin-bottom:14px}
.option h3{margin:0 0 4px;color:var(--ink);font-size:16px}
.option p{margin:0;font-size:13.5px}

/* ---- forms ---- */
form{display:flex;flex-direction:column;gap:14px}
label.field-label{font-size:13px;font-weight:600;color:var(--ink);margin-bottom:-6px}
input[type=text],input[type=password],input[type=url],input[type=number],input[type=file]{
  padding:11px 13px;border:1.5px solid var(--border);border-radius:10px;font-size:15px;width:100%;font-family:inherit;
  transition:border-color .15s;background:#fbfcfe}
input:focus{outline:none;border-color:var(--blue-500);background:#fff}
.checkbox-row{display:flex;align-items:flex-start;gap:9px;font-size:14px;color:var(--ink);background:#f8faff;border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.checkbox-row input{width:auto;margin-top:2px}
.checkbox-row .sub{color:var(--muted);font-size:12.5px;display:block;margin-top:2px}
.field-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
button{background:var(--blue-600);color:#fff;border:none;border-radius:10px;padding:12px 20px;font-size:15px;cursor:pointer;font-weight:600;transition:.15s}
button:hover{background:#1c46d6;box-shadow:0 6px 16px rgba(43,95,255,.28)}

.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.flash{background:#fff3cd;border:1px solid #ffe08a;color:#7a5b00;padding:10px 14px;border-radius:10px;margin-bottom:14px;font-size:14px}
table{width:100%;border-collapse:collapse}
td,th{padding:11px 10px;border-bottom:1px solid #edf0f5;text-align:left;font-size:14px;vertical-align:top}
th{background:#f8fafc;color:var(--muted);font-weight:600;font-size:12.5px;text-transform:uppercase;letter-spacing:.02em}
tr:hover td{background:#fafbff}

.pill{display:inline-block;padding:3px 10px;border-radius:999px;background:#eef3ff;font-size:12px;font-weight:600;color:var(--blue-600)}
.badge{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600}
.badge-website{background:#eef3ff;color:var(--blue-600)}
.badge-pdf{background:#fdeceb;color:#c53030}
.badge-research{background:#e9f8ef;color:var(--good)}
.score-good{color:var(--good)} .score-warn{color:var(--warn)} .score-bad{color:var(--bad)}
.back-link{color:#cfe0ff;font-size:13.5px}
"""


def _score_class(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if v >= 75:
        return "score-good"
    if v >= 50:
        return "score-warn"
    return "score-bad"


def _type_badge(t):
    label = {"website": "🔗 Website", "pdf": "📄 PDF", "research": "🔎 Research"}.get(t, t or "-")
    cls = {"website": "badge-website", "pdf": "badge-pdf", "research": "badge-research"}.get(t, "badge-website")
    from html import escape
    return f'<span class="badge {cls}">{escape(label)}</span>'


def hero(badge, title, subtitle, pill=None, show_logout=True):
    from html import escape
    pill_html = f'<span class="hero-pill">{escape(pill)}</span>' if pill else ""
    logout_html = (f'<a class="hero-logout" href="{url_for("logout")}">Log out</a>'
                   if show_logout else "")
    return f'''<div class="hero"><div class="hero-inner">
<div><span class="hero-badge">{escape(badge)}</span><h1>{title}</h1><p>{escape(subtitle)}</p></div>
<div class="hero-right">{pill_html}{logout_html}</div>
</div></div>'''

LOGIN_TMPL = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sriya Web Intelligence — Login</title>
<style>{{ css }}
body{display:flex;min-height:100vh;align-items:center;justify-content:center;
  background:radial-gradient(120% 160% at 50% 0%,#1b2a63 0%,var(--navy-900) 45%,#f5f7fb 45%)}
</style></head><body>
<div class="wrap" style="max-width:400px;padding:0 20px">
<div style="text-align:center;margin-bottom:22px">
<span class="hero-badge" style="color:#1b2a63;background:#fff;border-color:#fff">⚡ Sriya Web Intelligence</span>
<h1 style="color:#0b1330">Sign in</h1><p class="muted">Access your scans, reports &amp; product research</p>
</div>
{% with messages = get_flashed_messages() %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endwith %}
<div class="card">
<form method="post">
<label class="field-label">Username</label>
<input type="text" name="username" placeholder="Username" required autofocus>
<label class="field-label">Password</label>
<input type="password" name="password" placeholder="Password" required>
<button type="submit">Log in</button>
</form>
</div></div></body></html>
"""

HOME_TMPL = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sriya Web Intelligence — Home</title>
<style>{{ css }}</style></head><body>
{{ hero | safe }}
<div class="wrap">
<div class="options">
<a class="option" href="{{ url_for('dashboard') }}"><div class="emoji">📊</div><h3>Dashboard</h3><p class="muted">Browse every report generated so far, newest first</p></a>
<a class="option" href="{{ url_for('website_form') }}"><div class="emoji">🔗</div><h3>Website Link</h3><p class="muted">Full PDP audit — SEO, accessibility, security, performance &amp; conversion</p></a>
<a class="option" href="{{ url_for('pdf_form') }}"><div class="emoji">📄</div><h3>Dashboard PDF</h3><p class="muted">Upload a dashboard PDF/image, extract text &amp; metrics via OCR</p></a>
<a class="option" href="{{ url_for('research_form') }}"><div class="emoji">🔎</div><h3>Product Research</h3><p class="muted">Live web search for reviews, other listings &amp; mentions of a product</p></a>
<a class="option" href="{{ url_for('dashboards_ask') }}"><div class="emoji">🧭</div><h3>Ask Your Dashboards</h3><p class="muted">Search everything ingested from your dashboard PDFs and get the surrounding data</p></a>
</div></div></body></html>
"""

WEBSITE_FORM_TMPL = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Scan a website link</title>
<style>{{ css }}</style></head><body>
{{ hero | safe }}
<div class="wrap">
<a class="muted back-link-dark" href="{{ url_for('home') }}" style="color:#687386">&larr; Home</a>
{% with messages = get_flashed_messages() %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endwith %}
<div class="card">
<form method="post">
<label class="field-label">Product page URL</label>
<input type="url" name="url" placeholder="https://example.com/product/abc" required autofocus>
<label class="checkbox-row"><input type="checkbox" name="use_llm">
<span>Use LLM enrichment<span class="sub">Needs an API key configured in .env</span></span></label>
<label class="checkbox-row"><input type="checkbox" name="research" checked>
<span>Also run Product Research<span class="sub">Live web search for reviews, other retailer listings, forum &amp; video mentions of this exact product — separate from the on-page audit above</span></span></label>
<div class="field-row" id="research-terms-row">
<div><label class="field-label">Extra research terms <span class="muted" style="font-weight:400">(optional)</span></label>
<input type="text" name="research_terms" placeholder="e.g. review, model number"></div>
</div>
<button type="submit">Run scan</button>
</form>
</div></div></body></html>
"""

PDF_FORM_TMPL = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ingest a dashboard PDF</title>
<style>{{ css }}</style></head><body>
{{ hero | safe }}
<div class="wrap">
<a class="muted" href="{{ url_for('home') }}" style="color:#687386">&larr; Home</a>
{% with messages = get_flashed_messages() %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endwith %}
<div class="card">
<form method="post" enctype="multipart/form-data">
<label class="field-label">Dashboard PDF or image</label>
<input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff" required>
<span class="muted" style="font-size:12.5px">Accepts .pdf, .png, .jpg, .jpeg, .webp, .bmp, .tiff</span>
<button type="submit">Ingest &amp; generate report</button>
</form>
</div></div></body></html>
"""

DASHBOARD_TMPL = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dashboard</title>
<style>{{ css }}</style></head><body>
{{ hero | safe }}
<div class="wrap wide">
<a class="muted" href="{{ url_for('home') }}" style="color:#687386">&larr; Home</a>
<div class="kpis" style="margin-top:16px">
<div class="kpi"><div class="k-label">📊 Total reports</div><div class="k-value">{{ entries|length }}</div></div>
<div class="kpi"><div class="k-label">🔗 Website scans</div><div class="k-value">{{ counts.website }}</div></div>
<div class="kpi"><div class="k-label">📄 PDF ingests</div><div class="k-value">{{ counts.pdf }}</div></div>
<div class="kpi"><div class="k-label">🔎 Product research</div><div class="k-value">{{ counts.research }}</div></div>
</div>
<div class="card">
<table>
<tr><th>When</th><th>Type</th><th>Target</th><th>Health</th><th>Files</th></tr>
{% for e in entries %}
<tr>
<td>{{ e.created_at[:19].replace('T',' ') }}</td>
<td>{{ badge(e.type) | safe }}</td>
<td style="max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ e.target }}</td>
<td class="{{ score_class(e.overall_health) }}">{{ '%.0f'|format(e.overall_health) if e.overall_health is not none else '-' }}</td>
<td>
{% if e.html %}<a href="{{ url_for('serve_file', subpath=e.html) }}" target="_blank">HTML</a>{% endif %}
{% if e.pdf %} · <a href="{{ url_for('serve_file', subpath=e.pdf) }}" target="_blank">PDF</a>{% endif %}
{% if e.json %} · <a href="{{ url_for('serve_file', subpath=e.json) }}" target="_blank">JSON</a>{% endif %}
{% if e.type == 'pdf' and e.source_file %} · <a href="{{ url_for('dashboards_ask', source=e.source_file, scope='this') }}">🧭 Ask</a>{% endif %}
</td>
</tr>
{% else %}
<tr><td colspan="5" class="muted">No reports yet. Try "Website Link", "Dashboard PDF" or "Product Research" from the home page.</td></tr>
{% endfor %}
</table>
</div></div></body></html>
"""

RESEARCH_FORM_TMPL = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Product Research</title>
<style>{{ css }}</style></head><body>
{{ hero | safe }}
<div class="wrap">
<a class="muted" href="{{ url_for('home') }}" style="color:#687386">&larr; Home</a>
{% with messages = get_flashed_messages() %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endwith %}
<div class="card">
<form method="post">
<div class="field-row">
<div><label class="field-label">Product name</label>
<input type="text" name="product_name" placeholder="e.g. Realme 16T 5G" required autofocus></div>
<div><label class="field-label">Brand <span class="muted" style="font-weight:400">(optional)</span></label>
<input type="text" name="brand" placeholder="e.g. Realme"></div>
</div>
<div class="field-row">
<div><label class="field-label">Extra terms <span class="muted" style="font-weight:400">(optional)</span></label>
<input type="text" name="extra_terms" placeholder="e.g. review, 128GB"></div>
<div><label class="field-label">Max results</label>
<input type="number" name="num_results" value="8" min="1" max="20"></div>
</div>
<button type="submit">Search the web</button>
</form>
</div>
<p class="muted" style="font-size:13px">Runs a live web search (DuckDuckGo, or Bing if <code>BING_SEARCH_KEY</code> is set) and buckets results into
retailer listings, reviews/comparisons, videos, forum mentions and other references — with any prices found in the
snippets. Directional signal only, not a verified price feed.</p>
</div></body></html>
"""

ASK_TMPL = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ask Your Dashboards</title>
<style>{{ css }}</style></head><body>
{{ hero | safe }}
<div class="wrap wide">
<a class="muted" href="{{ url_for('home') }}" style="color:#687386">&larr; Home</a>
{% with messages = get_flashed_messages() %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endwith %}
<div class="card">
<form method="get">
<label class="field-label">What do you want to know?</label>
<input type="text" name="q" value="{{ q or '' }}" placeholder='e.g. "current DXI" or "Promocodeusagerate"' required autofocus>
{% if pdf_source %}
<div class="checkbox-row"><input type="checkbox" name="scope" value="this" {% if scope=='this' %}checked{% endif %}>
<span>Search only <b>{{ source_label }}</b><span class="sub">Untick to search every dashboard you've ever uploaded</span></span></div>
<input type="hidden" name="source" value="{{ pdf_source }}">
{% endif %}
<label class="checkbox-row"><input type="checkbox" name="summarize" {% if summarize %}checked{% endif %}>
<span>Write an AI answer from the matches<span class="sub">Needs GEMINI_API_KEY in .env — silently skipped otherwise, results below are unaffected</span></span></label>
<button type="submit">Search</button>
</form>
</div>

{% if searched %}
<div class="kpis">
<div class="kpi"><div class="k-label">Dashboards hit</div><div class="k-value">{{ result.dashboards_hit|length }}</div></div>
<div class="kpi"><div class="k-label">Matched chunks</div><div class="k-value">{{ result.matched_chunks|length }}</div></div>
<div class="kpi"><div class="k-label">Surrounding data</div><div class="k-value">{{ result.surrounding_chunks|length }}</div></div>
<div class="kpi"><div class="k-label">Metrics found</div><div class="k-value">{{ result.all_metrics_found|length }}</div></div>
</div>

{% if result.ai_answer_available %}
<div class="card" style="border-top:3px solid var(--blue-500)"><h2 style="margin-top:0">🤖 AI Answer</h2><p>{{ result.ai_answer }}</p></div>
{% elif summarize %}
<div class="card"><p class="muted">AI answer unavailable (no GEMINI_API_KEY set, or the call failed) — structured results below are unaffected.</p></div>
{% endif %}

{% if not result.matched_chunks %}
<div class="card"><p class="muted">No matches for "{{ result.query }}" in the ingested dashboard corpus (exact or semantic). Try a different term, or ingest more dashboards from the "Dashboard PDF" page.</p></div>
{% else %}
<div class="card"><h2 style="margin-top:0">Matched text</h2>
<table><tr><th>Dashboard</th><th>Page</th><th>Match</th><th>Text</th></tr>
{% for m in result.matched_chunks %}
<tr><td>{{ m.dashboard_name }}</td><td>{{ m.page }}</td>
<td><span class="pill">{{ m.match_type }} {{ '%.2f'|format(m.score) if m.match_type=='semantic' else '' }}</span></td>
<td>{{ m.text }}{% if m.metrics_found %}<br><small class="muted">Metrics: {{ m.metrics_found|join(', ') }}</small>{% endif %}</td></tr>
{% endfor %}
</table></div>

{% if result.surrounding_chunks %}
<div class="card"><h2 style="margin-top:0">Surrounding data on the same card / table</h2>
<table><tr><th>Dashboard</th><th>Page</th><th>Text</th></tr>
{% for s in result.surrounding_chunks %}
<tr><td>{{ s.dashboard_name }}</td><td>{{ s.page }}</td><td>{{ s.text }}</td></tr>
{% endfor %}
</table></div>
{% endif %}

{% if result.all_metrics_found %}
<div class="card"><h2 style="margin-top:0">All numeric / metric values found</h2>
{% for metric in result.all_metrics_found %}<span class="pill" style="margin:3px">{{ metric }}</span>{% endfor %}
</div>
{% endif %}
{% endif %}
{% endif %}
</div></body></html>
"""

ERROR_TMPL = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Error</title>
<style>{{ css }}</style></head><body>
{{ hero | safe }}
<div class="wrap">
<div class="card"><p>{{ message }}</p>{% if detail %}<pre style="white-space:pre-wrap;font-size:12px;color:#687386">{{ detail }}</pre>{% endif %}</div>
</div></body></html>
"""


def render(tmpl, hero_html="", **ctx):
    return render_template_string(
        tmpl, css=BASE_CSS, hero=hero_html, badge=_type_badge, score_class=_score_class, **ctx)


# -------------------------------------------------------------- routes ----

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if secrets.compare_digest(u, WEBAPP_USERNAME) and secrets.compare_digest(p, WEBAPP_PASSWORD):
            session["logged_in"] = True
            session["username"] = u
            return redirect(request.args.get("next") or url_for("home"))
        flash("Invalid username or password.")
    return render(LOGIN_TMPL)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    return render(HOME_TMPL, hero_html=hero(
        "⚡ Web Intelligence Suite", "Sriya Web Intelligence",
        "Choose what you want to generate a report from — audit a product page, ingest a "
        "dashboard PDF, or research where a product shows up across the web.",
        pill=f"👤 {session.get('username','')}"))


@app.route("/dashboard")
@login_required
def dashboard():
    entries = _load_index()
    counts = {"website": 0, "pdf": 0, "research": 0}
    for e in entries:
        if e.get("type") in counts:
            counts[e["type"]] += 1
    return render(DASHBOARD_TMPL, entries=entries, counts=counts, hero_html=hero(
        "📊 All Reports", "Dashboard",
        "Every report generated from Website Link, Dashboard PDF and Product Research, newest first."))


@app.route("/files/<path:subpath>")
@login_required
def serve_file(subpath):
    return send_from_directory(REPORTS_DIR, subpath)


def _run_website_scan(url_in: str, use_llm: bool = False, do_research: bool = False,
                       research_terms: str | None = None):
    """Runs the full audit pipeline for one URL, writes report.html/json/pdf,
    adds a dashboard index entry, and returns (report, rid, research_note,
    skip_reason). skip_reason is set (report=None) if the URL was skipped
    (blocked robots.txt, non-product page, etc). Shared by the HTML form
    route and the JSON API so both always produce identical output."""
    core_report = core.scan_url(url_in, use_llm=use_llm, force_render=False, check_links=False)
    if core_report.skipped:
        return None, None, None, core_report.skip_reason

    soup, content, _used_render = core.fetch_and_extract(url_in, force_render=False)
    response, _err = pro.fetch_headers(url_in)
    report = pro.build_report(url_in, soup, content, response, core_report)

    research_note = None
    if do_research:
        pname, pbrand = pro.product_identity(soup, url_in)
        if pname:
            rr = product_research.research_product(
                pname, brand=pbrand, num_results=8, extra_terms=research_terms)
            report.product_research = product_research.to_dict(rr)
            research_note = rr.reference_summary[0] if rr.reference_summary else None
        else:
            research_note = "Product Research skipped: could not determine a product name/title from this page."

    rid, out_dir = _new_report_dir()
    rendered_html = pro.html_report(report)
    (out_dir / "report.html").write_text(rendered_html, encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    pdf_path = out_dir / "report.pdf"
    pdf_export.try_html_to_pdf(rendered_html, pdf_path, label="website scan")

    _add_report({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "type": "website",
        "target": url_in,
        "overall_health": report.scores.get("overall_health_score"),
        "html": f"{rid}/report.html",
        "json": f"{rid}/report.json",
        "pdf": f"{rid}/report.pdf" if pdf_path.exists() else None,
    })
    return report, rid, research_note, None


@app.route("/website", methods=["GET", "POST"])
@login_required
def website_form():
    if request.method == "GET":
        return render(WEBSITE_FORM_TMPL, hero_html=hero(
            "🔗 Website Link", "Scan a product page",
            "Runs the full audit — semantic issues, spelling, SEO, accessibility, security, "
            "performance and conversion — and can optionally research this exact product's "
            "footprint across the rest of the web in the same run."))

    url_in = (request.form.get("url") or "").strip()
    use_llm = bool(request.form.get("use_llm"))
    do_research = bool(request.form.get("research"))
    research_terms = (request.form.get("research_terms") or "").strip() or None
    if not url_in:
        flash("Enter a URL to scan.")
        return redirect(url_for("website_form"))

    try:
        report, rid, research_note, skip_reason = _run_website_scan(
            url_in, use_llm=use_llm, do_research=do_research, research_terms=research_terms)
        if skip_reason:
            flash(f"Skipped: {skip_reason}")
            return redirect(url_for("website_form"))
        return redirect(url_for("serve_file", subpath=f"{rid}/report.html"))
    except Exception as e:
        return render(ERROR_TMPL, message=f"Scan failed for {url_in}: {e}",
                       detail=traceback.format_exc(),
                       hero_html=hero("⚠️ Error", "Something went wrong", "The scan could not be completed.")), 500


def _run_pdf_ingest(saved_path: Path, safe_name: str):
    """Ingests one dashboard PDF/image, writes report.html/json/pdf, adds a
    dashboard index entry, and returns (chunks, result, rid, corpus_size).
    Shared by the HTML form route and the JSON API."""
    chunks, result = ingest.ingest_file(str(saved_path))
    corpus_size = ingest.add_to_corpus(chunks, ingest.DEFAULT_CORPUS_PATH)

    rid, out_dir = _new_report_dir()
    rendered_html = _pdf_dashboard_html(safe_name, chunks, result, corpus_size)
    (out_dir / "report.html").write_text(rendered_html, encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps({"result": asdict(result), "chunks": [asdict(c) for c in chunks]},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    pdf_path = out_dir / "report.pdf"
    pdf_export.try_html_to_pdf(rendered_html, pdf_path, label="PDF ingestion report")

    _add_report({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "type": "pdf",
        "target": safe_name,
        "overall_health": None,
        "source_file": result.source_file,
        "html": f"{rid}/report.html",
        "json": f"{rid}/report.json",
        "pdf": f"{rid}/report.pdf" if pdf_path.exists() else None,
    })
    return chunks, result, rid, corpus_size


def _save_upload(f) -> tuple[Path, str] | tuple[None, None]:
    """Validates + saves an uploaded werkzeug FileStorage. Returns
    (saved_path, safe_name) or (None, None) if invalid."""
    if not f or not f.filename:
        return None, None
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        return None, None
    safe_name = secure_filename(f.filename)
    saved_path = UPLOADS_DIR / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    f.save(saved_path)
    return saved_path, safe_name


@app.route("/pdf", methods=["GET", "POST"])
@login_required
def pdf_form():
    if request.method == "GET":
        return render(PDF_FORM_TMPL, hero_html=hero(
            "📄 Dashboard PDF", "Upload a dashboard PDF",
            "Extracts text/metrics via the text-layer + OCR pipeline and adds it to the "
            "searchable corpus, then produces a dashboard summary report."))

    f = request.files.get("file")
    saved_path, safe_name = _save_upload(f)
    if saved_path is None:
        flash("Choose a file to upload." if not f or not f.filename
              else f"Unsupported file type: {Path(f.filename).suffix.lower()}")
        return redirect(url_for("pdf_form"))

    try:
        _chunks, _result, rid, _corpus_size = _run_pdf_ingest(saved_path, safe_name)
        return redirect(url_for("serve_file", subpath=f"{rid}/report.html"))
    except Exception as e:
        return render(ERROR_TMPL, message=f"PDF ingestion failed for {safe_name}: {e}",
                       detail=traceback.format_exc(),
                       hero_html=hero("⚠️ Error", "Something went wrong", "The PDF could not be ingested.")), 500


def _run_dashboard_ask(q: str, pdf_source: str | None = None, scope: str = "all",
                        summarize: bool = False):
    """Runs a search over the ingested-dashboard corpus and returns a
    dashboard_search.SearchResult (or None if the corpus is empty). Shared by
    the HTML route and the JSON API."""
    index = dsearch.DashboardIndex(ingest.DEFAULT_CORPUS_PATH)
    if index.is_empty():
        return None
    result = index.search(q)
    if pdf_source and scope == "this":
        result = _scope_to_source(result, pdf_source)
    if summarize:
        result = dsearch.summarize_with_llm(result)
    return result


@app.route("/dashboards/ask", methods=["GET"])
@login_required
def dashboards_ask():
    """Search everything ingested from dashboard PDFs/images (dashboard_search.py's
    TF-IDF + exact-match index over dashboard_corpus.json). Kept as its own
    page, separate from Product Research (which is a live web search, not a
    search over your own uploaded dashboards)."""
    q = (request.args.get("q") or "").strip()
    pdf_source = (request.args.get("source") or "").strip() or None
    scope = request.args.get("scope") or ("this" if pdf_source else "all")
    summarize = bool(request.args.get("summarize"))

    source_label = Path(pdf_source).name.split("_", 1)[-1] if pdf_source else None
    ctx = dict(q=q, pdf_source=pdf_source, scope=scope, source_label=source_label,
               summarize=summarize, searched=False, result=None)
    hero_html = hero("🧭 Ask Your Dashboards", "Search your ingested dashboards",
                      "Exact + semantic search over everything you've uploaded on the "
                      "\"Dashboard PDF\" page, with the surrounding label/value data pulled "
                      "in from the same card or table.")

    if not q:
        return render(ASK_TMPL, hero_html=hero_html, **ctx)

    try:
        result = _run_dashboard_ask(q, pdf_source, scope, summarize)
        if result is None:
            flash("No dashboards ingested yet. Upload one from the \"Dashboard PDF\" page first.")
            return render(ASK_TMPL, hero_html=hero_html, **ctx)

        ctx.update(searched=True, result=result)
        return render(ASK_TMPL, hero_html=hero_html, **ctx)
    except Exception as e:
        return render(ERROR_TMPL, message=f"Dashboard search failed for {q!r}: {e}",
                       detail=traceback.format_exc(),
                       hero_html=hero("⚠️ Error", "Something went wrong", "The search could not be completed.")), 500


def _scope_to_source(result: "dsearch.SearchResult", source: str) -> "dsearch.SearchResult":
    """Narrow an already-computed SearchResult down to chunks from one
    ingested file, recomputing the derived dashboards_hit/all_metrics_found
    fields to match -- used for the 'search only this dashboard' toggle."""
    result.matched_chunks = [m for m in result.matched_chunks if m.source_file == source]
    result.surrounding_chunks = [s for s in result.surrounding_chunks if s.source_file == source]
    result.dashboards_hit = sorted({m.dashboard_name for m in result.matched_chunks} |
                                    {s.dashboard_name for s in result.surrounding_chunks})
    metrics: list = []
    for m in result.matched_chunks + result.surrounding_chunks:
        for metric in m.metrics_found:
            if metric not in metrics:
                metrics.append(metric)
    result.all_metrics_found = metrics
    return result


def _run_product_research(product_name: str, brand: str | None = None,
                           extra_terms: str | None = None, num_results: int = 8):
    """Runs a live web search for one product, writes report.html/json/pdf,
    adds a dashboard index entry, and returns (rr, rid). Shared by the HTML
    route and the JSON API."""
    rr = product_research.research_product(
        product_name, brand=brand, num_results=num_results, extra_terms=extra_terms)

    rid, out_dir = _new_report_dir()
    rendered_html = _research_report_html(product_name, brand, rr)
    (out_dir / "report.html").write_text(rendered_html, encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(product_research.to_dict(rr), indent=2, ensure_ascii=False), encoding="utf-8")
    pdf_path = out_dir / "report.pdf"
    pdf_export.try_html_to_pdf(rendered_html, pdf_path, label="product research report")

    _add_report({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "type": "research",
        "target": rr.query or product_name,
        "overall_health": None,
        "html": f"{rid}/report.html",
        "json": f"{rid}/report.json",
        "pdf": f"{rid}/report.pdf" if pdf_path.exists() else None,
    })
    return rr, rid


@app.route("/research", methods=["GET", "POST"])
@login_required
def research_form():
    """Standalone Product Research: given just a product name (and optional
    brand/extra terms), runs product_research.research_product() directly --
    no page scan required. This is the generic version of the same feature
    website_form() runs inline against a scanned page's own product."""
    if request.method == "GET":
        return render(RESEARCH_FORM_TMPL, hero_html=hero(
            "🔎 Product Research", "Research a product across the web",
            "Live web search for reviews, other retailer listings, comparison articles, "
            "forum/video mentions and any prices mentioned -- for any product, not just one "
            "you've scanned a page for."))

    product_name = (request.form.get("product_name") or "").strip()
    brand = (request.form.get("brand") or "").strip() or None
    extra_terms = (request.form.get("extra_terms") or "").strip() or None
    try:
        num_results = int(request.form.get("num_results") or 8)
    except ValueError:
        num_results = 8
    num_results = max(1, min(20, num_results))

    if not product_name:
        flash("Enter a product name to research.")
        return redirect(url_for("research_form"))

    try:
        _rr, rid = _run_product_research(product_name, brand, extra_terms, num_results)
        return redirect(url_for("serve_file", subpath=f"{rid}/report.html"))
    except Exception as e:
        return render(ERROR_TMPL, message=f"Product research failed for {product_name!r}: {e}",
                       detail=traceback.format_exc(),
                       hero_html=hero("⚠️ Error", "Something went wrong", "The research run could not be completed.")), 500


def _pdf_dashboard_html(name, chunks, result: "ingest.IngestResult", corpus_size: int) -> str:
    from html import escape
    from urllib.parse import quote_plus
    metrics = [m for c in chunks for m in c.metrics_found]
    rows = "".join(
        f"<tr><td>{c.page}</td><td>{escape(c.extraction_method)}</td>"
        f"<td>{escape(c.text[:160])}</td><td>{escape(', '.join(c.metrics_found) or '-')}</td></tr>"
        for c in chunks[:200]
    )
    warnings = "".join(f"<li>{escape(w)}</li>" for w in result.warnings) or "<li>None</li>"
    ask_url = f"/dashboards/ask?source={quote_plus(result.source_file)}&scope=this"
    hero_html = hero("📄 Dashboard PDF", f"Ingested: {name}",
                      "Text/metrics extracted via the text-layer + OCR pipeline and added to the searchable corpus.",
                      show_logout=False)
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard PDF Ingestion — {escape(name)}</title><style>{BASE_CSS}</style></head><body>
{hero_html}
<div class="wrap wide">
<div class="kpis">
<div class="kpi"><div class="k-label">Pages</div><div class="k-value">{result.pages}</div></div>
<div class="kpi"><div class="k-label">Chunks added</div><div class="k-value">{result.chunks_added}</div></div>
<div class="kpi"><div class="k-label">Metrics found</div><div class="k-value">{len(metrics)}</div></div>
<div class="kpi"><div class="k-label">Corpus size (total)</div><div class="k-value">{corpus_size}</div></div>
</div>
<div class="card" style="border-top:3px solid var(--blue-500)">
<h2 style="margin-top:0">🧭 Ask about this dashboard</h2>
<p class="muted" style="margin-top:-6px">Got a question about the data on this PDF? Search it directly.</p>
<form method="get" action="/dashboards/ask" style="flex-direction:row;gap:10px;flex-wrap:wrap">
<input type="text" name="q" placeholder='e.g. "current DXI" or "Promocodeusagerate"' required style="flex:1;min-width:220px">
<input type="hidden" name="source" value="{escape(result.source_file)}">
<input type="hidden" name="scope" value="this">
<button type="submit">Ask</button>
</form>
</div>
<div class="card"><h2 style="margin-top:0">Extraction methods</h2><ul>{"".join(f"<li>{escape(k)}: {v}</li>" for k, v in result.extraction_method_summary.items()) or "<li>None</li>"}</ul></div>
<div class="card"><h2 style="margin-top:0">Warnings</h2><ul>{warnings}</ul></div>
<div class="card"><h2 style="margin-top:0">Extracted content</h2><table><tr><th>Page</th><th>Method</th><th>Text</th><th>Metrics found</th></tr>{rows}</table></div>
</div></body></html>'''


def _research_report_html(product_name: str, brand: str | None, rr: "product_research.ResearchResult") -> str:
    """Bespoke executive-style report for a standalone Product Research run
    (KPI cards + bucket badges), reusing the same visual language as the
    audit/dashboard reports rather than the plain table product_research.py
    ships for embedding inside a scan report."""
    from html import escape
    label = " ".join(x for x in [brand, product_name] if x)
    bucket_labels = {
        "retailer_listing": ("🛒 Retailer listings", "badge-website"),
        "review_or_comparison": ("⭐ Reviews / comparisons", "badge-research"),
        "video": ("▶️ Video mentions", "badge-pdf"),
        "forum_or_community": ("💬 Forum / community", "badge-website"),
        "other_mention": ("🔗 Other mentions", "badge-research"),
    }
    kpis = f'''<div class="kpis">
<div class="kpi"><div class="k-label">Total references found</div><div class="k-value">{len(rr.hits)}</div></div>
<div class="kpi"><div class="k-label">Retailer listings</div><div class="k-value">{rr.bucket_counts.get("retailer_listing",0)}</div></div>
<div class="kpi"><div class="k-label">Reviews / comparisons</div><div class="k-value">{rr.bucket_counts.get("review_or_comparison",0)}</div></div>
<div class="kpi"><div class="k-label">Prices mentioned</div><div class="k-value">{len(rr.all_prices_found)}</div></div>
</div>'''
    if not rr.available:
        body = f'<div class="card"><p class="muted">No results ({escape(rr.backend)}): {escape(rr.error or "no hits")}</p></div>'
    else:
        rows = "".join(
            f'<tr><td>{_type_badge_raw(*bucket_labels.get(h.bucket, (h.bucket.replace("_"," "), "badge-website")))}</td>'
            f'<td><a href="{escape(h.url)}" target="_blank" rel="noopener">{escape(h.title)}</a>'
            f'<br><small class="muted">{escape(h.domain)}</small></td>'
            f'<td>{escape(h.snippet)}</td>'
            f'<td>{escape(", ".join(h.prices_found)) if h.prices_found else "-"}</td></tr>'
            for h in rr.hits
        )
        summary = "".join(f"<li>{escape(x)}</li>" for x in rr.reference_summary)
        body = f'''<div class="card"><h2 style="margin-top:0">Summary</h2><ul>{summary}</ul></div>
<div class="card"><h2 style="margin-top:0">References</h2>
<table><tr><th>Type</th><th>Result</th><th>Snippet</th><th>Prices seen</th></tr>{rows}</table></div>'''
    hero_html = hero("🔎 Product Research", f"Web references for \"{escape(label)}\"",
                      f"Live search via {escape(rr.backend)}. Directional signal only — not a verified "
                      "price-comparison feed, and not a claim of completeness.", show_logout=False)
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Product Research — {escape(label)}</title><style>{BASE_CSS}</style></head><body>
{hero_html}
<div class="wrap wide">{kpis}{body}</div></body></html>'''


def _type_badge_raw(label: str, cls: str) -> str:
    from html import escape
    return f'<span class="badge {cls}">{escape(label)}</span>'


# ================================================================== API ===
# JSON API for the React frontend (frontend/). Every endpoint below is a
# thin wrapper around the exact same helpers the HTML routes above use
# (_run_website_scan, _run_pdf_ingest, _run_product_research,
# _run_dashboard_ask), so the SPA and the plain-HTML pages always produce
# identical reports -- only the response format (JSON vs. redirect+HTML)
# differs. Session-cookie auth is shared with the HTML routes; the browser
# just needs `credentials: 'include'` on fetch() calls from the same origin
# (or through the Vite dev proxy, see frontend/vite.config.js).

def _entry_public(e: dict) -> dict:
    """Report-index entry reshaped for the API: adds ready-to-use URLs."""
    out = dict(e)
    for key in ("html", "pdf", "json"):
        if out.get(key):
            out[f"{key}_url"] = url_for("serve_file", subpath=out[key])
    return out


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or request.form
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if username == WEBAPP_USERNAME and password == WEBAPP_PASSWORD:
        session["logged_in"] = True
        session["username"] = username
        return jsonify(ok=True, username=username)
    return jsonify(ok=False, error="Incorrect username or password."), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.route("/api/me")
def api_me():
    if session.get("logged_in"):
        return jsonify(authenticated=True, username=session.get("username"))
    return jsonify(authenticated=False)


@app.route("/api/reports")
@api_login_required
def api_reports():
    entries = [_entry_public(e) for e in _load_index()]
    counts = {"website": 0, "pdf": 0, "research": 0}
    for e in entries:
        if e.get("type") in counts:
            counts[e["type"]] += 1
    return jsonify(ok=True, entries=entries, counts=counts)


@app.route("/api/reports/<rid>")
@api_login_required
def api_report_detail(rid):
    """Full JSON payload for one report (for an in-app report viewer),
    plus its index entry (type/target/dates/file URLs)."""
    entries = _load_index()
    entry = next((e for e in entries if (e.get("html") or "").split("/")[0] == rid
                  or (e.get("json") or "").split("/")[0] == rid), None)
    if entry is None:
        return jsonify(ok=False, error="Report not found."), 404
    json_path = REPORTS_DIR / rid / "report.json"
    if not json_path.exists():
        return jsonify(ok=False, error="Report data file missing."), 404
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify(ok=False, error=f"Could not read report: {e}"), 500
    return jsonify(ok=True, entry=_entry_public(entry), data=data)


@app.route("/api/scan/website", methods=["POST"])
@api_login_required
def api_scan_website():
    data = request.get_json(silent=True) or {}
    url_in = (data.get("url") or "").strip()
    if not url_in:
        return jsonify(ok=False, error="Enter a URL to scan."), 400
    use_llm = bool(data.get("use_llm"))
    do_research = bool(data.get("research"))
    research_terms = (data.get("research_terms") or "").strip() or None

    try:
        report, rid, research_note, skip_reason = _run_website_scan(
            url_in, use_llm=use_llm, do_research=do_research, research_terms=research_terms)
        if skip_reason:
            return jsonify(ok=False, error=f"Skipped: {skip_reason}"), 422
        return jsonify(ok=True, rid=rid, research_note=research_note,
                        report=asdict(report),
                        html_url=url_for("serve_file", subpath=f"{rid}/report.html"),
                        pdf_url=url_for("serve_file", subpath=f"{rid}/report.pdf"))
    except Exception as e:
        return jsonify(ok=False, error=f"Scan failed for {url_in}: {e}",
                        detail=traceback.format_exc()), 500


@app.route("/api/scan/pdf", methods=["POST"])
@api_login_required
def api_scan_pdf():
    f = request.files.get("file")
    saved_path, safe_name = _save_upload(f)
    if saved_path is None:
        if not f or not f.filename:
            return jsonify(ok=False, error="Choose a file to upload."), 400
        return jsonify(ok=False, error=f"Unsupported file type: {Path(f.filename).suffix.lower()}"), 400

    try:
        chunks, result, rid, corpus_size = _run_pdf_ingest(saved_path, safe_name)
        return jsonify(ok=True, rid=rid, corpus_size=corpus_size,
                        result=asdict(result),
                        chunk_count=len(chunks),
                        metrics_found=sorted({m for c in chunks for m in c.metrics_found}),
                        source_file=result.source_file,
                        html_url=url_for("serve_file", subpath=f"{rid}/report.html"),
                        pdf_url=url_for("serve_file", subpath=f"{rid}/report.pdf"))
    except Exception as e:
        return jsonify(ok=False, error=f"PDF ingestion failed for {safe_name}: {e}",
                        detail=traceback.format_exc()), 500


@app.route("/api/research", methods=["POST"])
@api_login_required
def api_research():
    data = request.get_json(silent=True) or {}
    product_name = (data.get("product_name") or "").strip()
    if not product_name:
        return jsonify(ok=False, error="Enter a product name to research."), 400
    brand = (data.get("brand") or "").strip() or None
    extra_terms = (data.get("extra_terms") or "").strip() or None
    try:
        num_results = int(data.get("num_results") or 8)
    except (TypeError, ValueError):
        num_results = 8
    num_results = max(1, min(20, num_results))

    try:
        rr, rid = _run_product_research(product_name, brand, extra_terms, num_results)
        return jsonify(ok=True, rid=rid, result=product_research.to_dict(rr),
                        html_url=url_for("serve_file", subpath=f"{rid}/report.html"),
                        pdf_url=url_for("serve_file", subpath=f"{rid}/report.pdf"))
    except Exception as e:
        return jsonify(ok=False, error=f"Product research failed for {product_name!r}: {e}",
                        detail=traceback.format_exc()), 500


@app.route("/api/ask")
@api_login_required
def api_ask():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(ok=False, error="Enter a question to search for."), 400
    pdf_source = (request.args.get("source") or "").strip() or None
    scope = request.args.get("scope") or ("this" if pdf_source else "all")
    summarize = request.args.get("summarize") in ("1", "true", "True")

    try:
        result = _run_dashboard_ask(q, pdf_source, scope, summarize)
        if result is None:
            return jsonify(ok=False, error='No dashboards ingested yet. Upload one from '
                                            '"Dashboard PDF" first.'), 422
        return jsonify(ok=True, result=asdict(result))
    except Exception as e:
        return jsonify(ok=False, error=f"Dashboard search failed for {q!r}: {e}",
                        detail=traceback.format_exc()), 500


# --------------------------------------------------------- SPA frontend ---
# Serves the built React app (frontend/dist, produced by `npm run build`
# inside frontend/). Falls back to the classic server-rendered HTML pages
# above if the frontend hasn't been built -- nothing here is required for
# the rest of webapp.py to keep working.

FRONTEND_DIST = APP_ROOT / "frontend" / "dist"


@app.route("/app")
@app.route("/app/")
@app.route("/app/<path:subpath>")
def spa(subpath=""):
    if not FRONTEND_DIST.exists():
        return ("The React frontend hasn't been built yet. Run `npm install && npm run build` "
                "inside the frontend/ folder, or use the classic pages at /, /website, /pdf, "
                "/research and /dashboards/ask in the meantime."), 404
    target = FRONTEND_DIST / subpath if subpath else None
    if target and target.is_file():
        return send_from_directory(FRONTEND_DIST, subpath)
    return send_file(FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("WEBAPP_PORT", "8005"))
    app.run(host="0.0.0.0", port=port, debug=False)
