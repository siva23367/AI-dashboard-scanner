# New Features — Research & Founder Positioning

Added on top of the existing Pro scanner (`pro_scanner.py`) without touching
its core rule engine. Four new modules, all wired in as optional CLI flags
so nothing breaks the existing workflow if you don't pass them.

| Module | What it adds | New CLI flags |
|---|---|---|
| `web_vitals.py` | **Real** Core Web Vitals (LCP/CLS/INP/TTFB) from Google's PageSpeed Insights API — actual Chrome-user field data where available, not HTML heuristics | `--real-vitals`, `--psi-key` |
| `revenue_impact.py` | Converts category scores into an estimated **$/month revenue-at-risk** number using cited industry benchmarks | `--monthly-visitors`, `--aov`, `--conversion-rate`, `--currency` |
| `trust_signals.py` | Detects conversion-psychology signals the old checker missed: urgency/scarcity, social proof, trust badges, payment logos, guest checkout, free-shipping messaging, cross-sell | (always on, part of the `conversion` category) |
| `competitor_compare.py` | Runs the same scan on your PDP + competitor PDPs, produces a side-by-side score table and a plain-English gap list | `--competitors url1 url2 ...` |
| `pdf_export.py` | Writes a `.pdf` version of the report (scan report and competitor benchmark) alongside the existing `.json`/`.html`, by printing the same HTML through headless Chromium | on by default, `--no-pdf` to skip |

## Why these four, specifically (the "founder POV" reasoning)

A founder skimming a technical audit stops paying attention at "missing
`X-Content-Type-Options` header." The existing tool is a genuinely solid
rule engine, but everything it outputs is stated as **technical debt**. The
gap is translation: technical finding → business consequence → "how do we
compare to the competition" → "what do we do first."

1. **Real Core Web Vitals** — the old `performance_audit()` counts things
   like `loading="lazy"` attributes and script tags. That's a reasonable
   static proxy, but a founder (or their board) will eventually ask "what
   does Google PageSpeed actually say," because that's the number that
   shows up in Search Console and affects rankings. Shipping this from
   day one avoids a credibility gap the first time someone runs Lighthouse
   themselves and gets a different number than the old heuristic implied.

2. **Revenue Impact** — this is the single highest-leverage addition. A
   founder does not act on "your CSP header is missing." A founder acts on
   "this is a directional $10K/month opportunity, here's the receipt."
   The multipliers are not invented — they're capped, conservative
   fractions of numbers that are already published and citable:
   - Each additional second of page load is associated with roughly a 7%
     drop in conversion (aggregate of 2025 studies incl. Reboot Online /
     Kanuka Digital); mobile abandonment climbs sharply past a 3-second
     load (Google / SiteBuilder Report data, widely cited across 2025-26
     performance research).
   - Baymard Institute's meta-analysis of checkout-usability studies finds
     the average large e-commerce site could recover on the order of
     ~35% more conversions by fixing solvable checkout friction; the
     global cart abandonment rate sits around 70% as of 2026.
   - The Visa / Stanford Digital Trust Lab's 2026 Cybersecurity and
     E-Commerce Trust Index found that showing SSL badges, recognizable
     payment logos, and a money-back guarantee together roughly halved
     security-related checkout abandonment (25.4% → 11.8%).
   - Forms/checkouts that display trust badges are commonly cited as
     seeing conversion lifts up into the 40%+ range in isolated tests.

   The model deliberately (a) caps each lever well below its headline
   number, (b) applies a 0.7 co-occurrence discount when stacking multiple
   simultaneous fixes (studies measure these levers mostly in isolation,
   not additively), and (c) ships every output with an explicit
   "directional estimate, not a guarantee, not financial advice, validate
   with your own A/B tests" disclaimer. The goal is a credible
   prioritization signal, not a number that could be mistaken for an
   audited financial claim.

3. **Trust / urgency / social-proof signals** — these are the specific,
   well-documented conversion-psychology levers (scarcity, social proof,
   trust badges, guest checkout, free-shipping messaging, cross-sell) that
   the original conversion audit didn't check for at all — it only checked
   "does a CTA/price/review exist," not "does the page use the persuasion
   techniques that are consistently cited in checkout-usability research."

4. **Competitor benchmarking** — the most persuasive artifact in almost any
   founder or investor conversation is comparative, not absolute. "We're
   at 76/100 on conversion readiness" is forgettable. "We're at 76,
   [competitor] is at 91, here's exactly what they do that we don't" is a
   roadmap a founder will actually forward to their team.

## Usage

```bash
# Full run: real vitals + revenue impact + competitor benchmark
python pro_scanner.py "https://yourstore.com/product/abc" \
  --real-vitals \
  --monthly-visitors 150000 --aov 60 --conversion-rate 0.028 \
  --competitors "https://competitor.com/product/xyz"
```

`--real-vitals` calls `googleapis.com` (PageSpeed Insights) — make sure
that domain is reachable from wherever you run this; it is not required
for the rest of the report to function.

## Honesty notes (please keep these when extending the tool)

- `web_vitals.py` clearly labels whether a metric came from real
  Chrome-user field data or a Lighthouse lab simulation (smaller/newer
  sites often don't have enough CrUX traffic for field data yet).
- `revenue_impact.py` always emits its `disclaimer` field; the HTML report
  renders it directly under the headline number. Don't strip it out for a
  cleaner-looking demo — the number is only trustworthy *with* the caveat.
- None of this claims to measure live user behavior, a security
  vulnerability, or guaranteed conversion lift from a static/black-box
  scan — consistent with the existing product-positioning note in
  `PRO_README.md`.
