# Sriya Web Intelligence — Frontend (React)

A React + Vite + Tailwind single-page app that sits in front of every script
in this project (Website Scan, Dashboard PDF ingest + search, Product
Research) via the JSON API added to `webapp.py`. The old server-rendered
HTML pages (`/`, `/website`, `/pdf`, `/research`, `/dashboards/ask`,
`/dashboard`) still work exactly as before — this is an additional, nicer
way to use the same backend, not a replacement.

## Run it in development (hot reload)

```bash
# terminal 1 — the Flask backend, as usual
cd ..
source .venv/bin/activate
python webapp.py            # defaults to http://127.0.0.1:8005

# terminal 2 — the frontend dev server
cd frontend
npm install                 # first time only
npm run dev                 # http://127.0.0.1:5173
```

Open **http://127.0.0.1:5173** — it proxies `/api` and `/files` calls to
Flask automatically (see `vite.config.js`), so there's no CORS to configure.
If your Flask backend runs on a different port, set `FLASK_DEV_TARGET`:

```bash
FLASK_DEV_TARGET=http://127.0.0.1:8005 npm run dev
```

## Build for production (served by Flask itself)

```bash
cd frontend
npm install
npm run build
```

This writes `frontend/dist/`. `webapp.py` automatically serves it at
**`/app`** — just start Flask as usual and open `http://127.0.0.1:8005/app`.
No separate frontend server needed in production; one process, one port.

## What's here

- `src/api.js` — the only file that talks to the backend (fetch wrapper for
  `/api/*`).
- `src/AuthContext.jsx` — session-cookie auth state shared across the app.
- `src/pages/` — one file per screen: `Home`, `WebsiteScan`, `PdfIngest`,
  `ProductResearch`, `AskDashboards`, `Reports`, `Login`.
- `src/components/ui.jsx` — shared primitives (`Card`, `KpiCard`, `Badge`,
  `Button`, `EmptyState`, the `ScanSweep` loading indicator).
- `src/components/results.jsx` — shared result renderers (health gauge,
  issue list, research hits, ask-dashboard result panel) used by more than
  one page so a website scan, a PDF ingest and an "ask" search all look and
  behave consistently.

## Design notes

- Palette/type tokens live in `tailwind.config.js` (navy + signal-blue
  brand, Space Grotesk for headings, IBM Plex Mono for KPI numbers).
- Two recurring signature touches tie the UI back to what the product
  actually does: a **scan-sweep** beam animation while a request is in
  flight, and **viewfinder corner brackets** that appear on hover over the
  main action tiles / drop zone (`.scan-sweep-*` and `.viewfinder` in
  `src/index.css`).
