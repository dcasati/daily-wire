"""Command line interface."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .fetch import FixtureFetcher, check_url, fetch, live_fetcher
from .models import load_yaml, log_event
from .pipeline import run
from .publish import health
from .summarize import CopilotCLI, OpenAICompat


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="daily-wire")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="generate and publish an edition")
    r.add_argument("--config", default="config/briefing.yaml")
    r.add_argument("--sources", default="config/sources.yaml")
    r.add_argument("--site", default="site")
    r.add_argument("--fixtures", help="read feeds from this directory instead of the network")
    r.add_argument("--now", help="ISO timestamp override (tests)")
    r.add_argument("--no-llm", action="store_true", help="deterministic evidence-only mode; no API key needed")
    r.add_argument("--label", help="visible label (e.g. TEST) added to the edition")
    r.add_argument("--require-hour", action="store_true", help="exit quietly unless local time is the configured publish hour (DST guard)")
    h = sub.add_parser("health", help="publication health check")
    h.add_argument("--config", default="config/briefing.yaml")
    h.add_argument("--site", default="site")
    c = sub.add_parser("check-sources", help="verify live feed URLs (needs network)")
    c.add_argument("--sources", default="config/sources.yaml")
    e = sub.add_parser("eval", help="run the fixture evaluation and print metrics")
    e.add_argument("--fixtures", default="tests/fixtures")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        cfg = load_yaml(a.config)
        now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
        if a.require_hour and now.astimezone(ZoneInfo(cfg["timezone"])).hour != cfg["publish_hour_local"]:
            log_event("skipped_wrong_hour", local=now.astimezone(ZoneInfo(cfg["timezone"])).isoformat())
            return 0
        sources = load_yaml(a.fixtures + "/sources.yaml" if a.fixtures else a.sources)["sources"]
        fetcher = FixtureFetcher(a.fixtures) if a.fixtures else live_fetcher
        kind = os.environ.get("DAILY_WIRE_PROVIDER") or cfg["llm"]["provider"]
        provider = None if (a.no_llm or kind == "dry-run") else {"openai_compat": OpenAICompat, "copilot_cli": CopilotCLI}[kind](cfg["llm"])
        res = run(cfg, sources, fetcher, now, Path(a.site), provider, a.label)
        summary = {k: res.get(k) for k in ("status", "reason", "edition", "sources_ok", "sources_total", "items")}
        if res["status"] == "published":
            b = res["briefing"]
            summary.update(mode=b["mode"], words=b["words"], usage=b["usage"], warnings=b["warnings"])
        print(json.dumps(summary, indent=1))
        return 0  # a stale run is not a failure; `health` reports freshness
    if a.cmd == "health":
        cfg = load_yaml(a.config)
        probs = health(Path(a.site), datetime.now(timezone.utc), cfg["max_age_hours_health"])
        print(json.dumps({"problems": probs}))
        return 1 if probs else 0
    if a.cmd == "check-sources":
        bad = 0
        for s in load_yaml(a.sources)["sources"]:
            try:
                check_url(s["url"])
                body, _ = fetch(s["url"], retries=0)
                print(f"OK    {s['id']} ({len(body or b'')} bytes)")
            except Exception as exc:  # noqa: BLE001
                bad += 1
                print(f"FAIL  {s['id']}: {exc}")
        return 1 if bad else 0
    if a.cmd == "eval":
        from .evaluate import evaluate

        res = evaluate(a.fixtures)
        print(json.dumps(res, indent=1))
        return 0 if res["passed"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
