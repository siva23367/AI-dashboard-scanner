# Gemini authentication fix

Your previous scan showed `invalid authentication credentials`.

Current Google guidance recommends the official `google-genai` SDK and `GEMINI_API_KEY` / `GOOGLE_API_KEY` environment variables. Newer Gemini documentation uses `gemini-3.6-flash`; the legacy `generateContent` API is still documented, but Google recommends the newer Interactions API for new projects.

## Quick local check

```bash
source .venv/bin/activate
python3 -c 'import os; print("GEMINI_API_KEY:", "SET" if os.getenv("GEMINI_API_KEY") else "MISSING")'
```

If missing:

```bash
export GROQ_API_KEY="YOUR_KEY"
```

Do not commit the key to Git.

If the key exists but authentication still fails, create/restrict a current Gemini API key in Google AI Studio and make sure the Gemini API is allowed for that key. Google says unrestricted standard keys are being rejected and that the migration to authorization keys is underway.
