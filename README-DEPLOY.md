# Deploying Sriya Web Intelligence — Vercel (frontend) + Render (backend)

Two separate deploys, one for each half of the app:

- **Frontend** (`frontend/`) — a static React build → **Vercel**.
- **Backend** (everything else, `webapp.py` + the scanners) — a Docker
  container with Flask, Playwright (headless Chromium) and Tesseract OCR →
  **Render**.

They talk to each other over plain HTTPS (`fetch` calls with a session
cookie), configured via a couple of env vars on each side. Nothing needs to
be built together — you can deploy/redeploy either half independently.

---

## Part A — Backend on Render

1. Push `Dockerfile`, `.dockerignore`, `render.yaml`, `requirements.txt`,
   `webapp.py`, `dashboard_ingest.py` (all included in this zip) to your repo.
2. **https://dashboard.render.com** → sign in with GitHub → **New +** →
   **Blueprint** → pick your repo. Render reads `render.yaml` and shows the
   `sriya-web-intelligence` service (Docker, 1 GB persistent disk).
3. **Apply**, then fill in the env vars it asks for:

   | Key | Value |
   |---|---|
   | `WEBAPP_USERNAME` | pick a real username (not `admin`) |
   | `WEBAPP_PASSWORD` | pick a strong password |
   | `WEBAPP_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` — paste the output |
   | `GROQ_API_KEY` | your Groq key, if you want LLM enrichment / AI answers |
   | `FRONTEND_ORIGIN` | leave blank for now — you'll set this in step 6, after Vercel gives you a URL |

   `CROSS_ORIGIN_COOKIES=1` and `DATA_DIR=/data` are already set by
   `render.yaml` — don't remove them, they're what make login work across
   two different domains and keep your reports/uploads/corpus across
   redeploys.

4. First deploy takes ~5–8 minutes (installing Chromium). Watch **Logs** for
   `Listening at: http://0.0.0.0:8005`.
5. Render gives you a backend URL like
   `https://sriya-web-intelligence.onrender.com` — copy it, you need it next.

## Part B — Frontend on Vercel

6. **https://vercel.com/new** → import the same GitHub repo.
7. Vercel will ask for the project settings — set:
   - **Root Directory**: `frontend`
   - **Framework Preset**: Vite (auto-detected once Root Directory is set)
   - **Build Command** / **Output Directory**: leave as-is — `frontend/vercel.json` already specifies `npm run build` → `dist`.
8. Add one environment variable before deploying:

   | Key | Value |
   |---|---|
   | `VITE_API_BASE_URL` | the Render URL from step 5, e.g. `https://sriya-web-intelligence.onrender.com` (no trailing slash) |

9. **Deploy**. Vercel gives you a URL like `https://your-app.vercel.app`.

## Part C — connect them

10. Go back to Render → your service → **Environment** → set
    `FRONTEND_ORIGIN` to your exact Vercel URL from step 9 (e.g.
    `https://your-app.vercel.app`, no trailing slash) → save (this triggers
    a redeploy, ~1 minute since it's just an env change).
11. Open your Vercel URL and log in. That's it — the frontend on Vercel is
    now calling the API on Render, with session cookies working cross-site
    (`SameSite=None; Secure`, both sides HTTPS).

**Every `git push`** redeploys both sides automatically (Render watches the
repo via the Blueprint; Vercel watches it via the import) — no extra steps
after this one-time setup.

### If login works locally but not after deploying

- `FRONTEND_ORIGIN` on Render must match your Vercel URL **exactly** —
  scheme, host, no trailing slash. A mismatch here is the #1 cause of
  "login succeeds but every next request looks logged out."
- Both must be HTTPS. `SameSite=None` cookies are rejected by browsers over
  plain HTTP — this is why `CROSS_ORIGIN_COOKIES` shouldn't be set to `1`
  for local dev (Vite's proxy avoids the whole cross-origin problem there).
- If you're using a Vercel *preview* deployment URL (not your main one),
  that's a different origin than production — either add it to
  `FRONTEND_ORIGIN` too (comma-separate isn't supported by the current
  single-origin CORS setup in `webapp.py` — change `origins=[FRONTEND_ORIGIN]`
  to a list of URLs if you need more than one), or just test against the
  production URL.

---

## Alternative: single Docker image (no Vercel)

If you'd rather have Flask serve the built React app itself instead of
using Vercel — one host, one process, no CORS/cookie config needed at all:

```dockerfile
# add back before the Python stage in Dockerfile:
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN VITE_BASE_PATH=/app/ npm run build

# ...then after `COPY . .` in the runtime stage, add:
COPY --from=frontend-build /frontend/dist ./frontend/dist
```

Also remove `frontend/` from `.dockerignore` in that case. `webapp.py`
already has the `/app` route ready to serve whatever's in `frontend/dist` —
no other code changes needed. Skip `FRONTEND_ORIGIN`/`CROSS_ORIGIN_COOKIES`
entirely (same-origin, no CORS needed), and open
`https://<your-render-app>.onrender.com/app`.

## Alternative: your own VPS with plain Docker (backend only)

```bash
git clone <your-repo-url>
cd files
docker build -t sriya-backend .
docker run -d \
  --name sriya \
  -p 8005:8005 \
  -v sriya_data:/data \
  -e DATA_DIR=/data \
  -e DASHBOARD_CORPUS_PATH=/data/dashboard_corpus.json \
  -e WEBAPP_USERNAME=youruser \
  -e WEBAPP_PASSWORD=yourpassword \
  -e WEBAPP_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -e GROQ_API_KEY=your_groq_key \
  -e FRONTEND_ORIGIN=https://your-app.vercel.app \
  -e CROSS_ORIGIN_COOKIES=1 \
  sriya-backend
```

Put Nginx or Caddy in front for HTTPS + your domain (Caddy is the least
config — a two-line Caddyfile gets you automatic Let's Encrypt certs). The
Vercel side (Part B above) works the same regardless of where the backend
is hosted, as long as `VITE_API_BASE_URL` points at it.
