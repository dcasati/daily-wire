# Daily Wire

Automated daily situational-awareness brief (≈400–600 words): geopolitical, military, security, cyber, infrastructure and disaster developments, organised by region, with numbered, clickable sources. Output: EPUB for a Kobo Aura One running KOReader, plus Markdown, JSON and an OPDS catalog, all served from GitHub Pages and built by GitHub Actions at 06:00 America/Edmonton.

Editorial product only: it is inspired by the *style* of concise, geographically organised briefings and reproduces no third-party content beyond cited headlines/links.

> **Status honesty.** Everything below was tested offline with synthetic fixtures (55 tests + fixture evaluation pass). **Not tested live:** real feed fetching, a real LLM call, GitHub Actions execution, GitHub Pages hosting, and KOReader download. Feed URLs in `config/sources.yaml` are marked `verified: false` until you run `daily-wire check-sources` from a networked machine.

## Quick start (local, no API key)

```bash
git clone <your-repo> daily-wire && cd daily-wire
python3 -m venv .venv && . .venv/bin/activate
pip install ".[dev]"
pytest -q                       # offline tests
daily-wire eval                 # fixture evaluation with pass/fail thresholds
daily-wire run --fixtures tests/fixtures --site /tmp/site --now 2026-10-30T12:00:00Z --no-llm \
  --label "TEST EDITION: synthetic fixtures"
ls /tmp/site /tmp/site/editions
```

A sample generated from fixtures is in [`docs/sample/`](docs/sample) (clearly labelled TEST).

## Deploy

1. Create a **public** GitHub repo and push this code to `main` (Pages on private repos needs a paid plan, and publishes publicly anyway; see [operations](docs/operations.md)).
2. Settings → Secrets and variables → Actions: add secret `DAILY_WIRE_API_KEY` (OpenAI-compatible provider). Optional variable `DAILY_WIRE_MODEL`. Check `config/briefing.yaml` (`llm.*` prices and `max_daily_usd`).
3. Run **Actions → daily-brief → Run workflow** once (this creates the `gh-pages` branch). Then Settings → Pages → *Deploy from a branch* → `gh-pages` / `/ (root)`.
4. Set `site.base_url` in `config/briefing.yaml` if you want absolute OPDS links (optional).
5. Without a key the workflow publishes the deterministic evidence-only edition.

## KOReader

File browser → ☰ (top menu) → **Search** icon / *OPDS catalog* → **+** → name `Daily Wire`, URL `https://<user>.github.io/<repo>/opds.xml` → open it and tap the newest edition to download. Optional: OPDS catalog → hold the catalog → *Sync*/auto-download is available in recent KOReader versions (see [operations](docs/operations.md)).

## Layout

`config/` sources + editorial config · `src/daily_wire/` pipeline (~1,400 lines) · `tests/` + `tests/fixtures/` · `docs/` architecture (ADR), editorial policy, operations, evaluation.

CLI: `daily-wire run | eval | health | check-sources`.
