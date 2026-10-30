# Operations

## Setup checklist
1. Public repo; push code. 2. Secret `DAILY_WIRE_API_KEY`; optional variable `DAILY_WIRE_MODEL`. 3. Run the workflow manually once (creates `gh-pages`). 4. Settings → Pages → branch `gh-pages`, `/ (root)`. 5. `daily-wire check-sources` locally (networked) and set `enabled: false` for any dead feed; fix `verified` flags.

Pages URL: `https://<user>.github.io/<repo>/`; OPDS: `…/opds.xml`; editions: `…/editions/briefing-YYYY-MM-DD.{epub,md,json}`; status: `…/status.json` (last success, mode, words, usage, warnings).
A custom domain later: add it in Pages settings and set `site.base_url`; nothing else changes.

## Using GitHub Copilot instead of an API key (untested live)
Set repository variable `DAILY_WIRE_PROVIDER=copilot_cli` (optionally `DAILY_WIRE_MODEL`, default `auto`) and secret `COPILOT_GITHUB_TOKEN` (fine-grained PAT from a Copilot-enabled account with the "Copilot Requests" permission; `GITHUB_TOKEN` cannot be used). The workflow installs `@github/copilot` and the pipeline calls `copilot -p` with no tools granted in an empty scratch directory. Set `llm.price_*_per_mtok` to 0 in `config/briefing.yaml`: usage is billed as Copilot premium requests (at most `llm.max_attempts` per day), and the CLI reports no token counts, so recorded usage is an estimate. If the CLI fails or its output fails verification, the evidence-only edition is published. Not tested here: the sandbox cannot reach the Copilot API.

## KOReader
1. Open the top menu → search/OPDS icon (*OPDS catalog*; menu names vary slightly by version).
2. **+** (add) → Name `Daily Wire`, URL = OPDS URL above (no credentials needed).
3. Open the catalog, tap the newest edition → *Download*. Files go to the download folder set in KOReader. Newer KOReader versions also offer OPDS *sync* of a catalog to a folder; enable it from the catalog's long-press menu if available. (Not tested on a device here.)
4. Device needs Wi-Fi at download time.

## Daily behaviour
- Schedule: 12:00 and 13:00 UTC; only the run at 06:xx America/Edmonton proceeds (`--require-hour`). Manual run: Actions → daily-brief → Run workflow (`no_llm` optional; manual runs ignore the hour guard).
- `published` → new edition. `stale` (no usable sources, or fallback failed verification) → nothing is published, previous edition stays; the job's health step fails once the latest edition is older than `max_age_hours_health` (36 h), so GitHub's failure email is your freshness alert.
- Reduced edition: banner "evidence-only" in the EPUB when LLM output failed verification or the budget was hit. Partial source outages show a coverage warning.
- Logs are JSON lines (`source_failed`, `quarantined_item`, `verification`, `collected`).

## Costs (estimates; assumptions stated)
- GitHub Actions/Pages: ~2 short runs/day (one exits immediately); well inside free tiers for a public repo.
- LLM: configured placeholder prices $0.15 / $0.60 per 1M input/output tokens (verify against your provider's current list). Worst case per call = 6,000 in + 1,200 out ≈ $0.0016; two attempts/day ≈ $0.003/day ≈ $0.10/month. Real usage is usually lower, and `max_daily_usd` (default $0.25) hard-stops spending. Real-run cost has **not** been measured; the per-edition `usage` block in the JSON/`status.json` records provider-reported tokens once you run it.

## Risks
- Feed URLs/terms change or block bots (unverified list). RSS summaries are short, so evidence is thin; the system prefers omission to inference.
- Lexical clustering can split or merge events; wire detection is heuristic.
- Public output; no access control. Model/provider outages → evidence-only edition.
- GitHub scheduled runs can be delayed or disabled after 60 days of repo inactivity (public repos); the daily commit to `gh-pages` does not count as activity on `main`, so make an occasional commit or re-enable the schedule.
- Single-point trust in feeds: a compromised feed can still publish false facts (attributed to it).
