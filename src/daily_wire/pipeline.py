"""Orchestrates stages A-G. Deterministic given (config, fetched data, now)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .changes import annotate, update_history
from .cluster import cluster
from .evidence import build_packets
from .models import load_json, log_event
from .normalize import collect_items
from .fetch import fetch_all
from .publish import publish
from .rank import score, shortlist
from .summarize import Budget, BudgetExceeded, Provider, evidence_only_write, llm_write
from .verify import verify


def run(cfg: dict, sources: list[dict], fetcher, now: datetime, site: Path, provider: Provider | None = None,
        label: str | None = None, do_publish: bool = True) -> dict:
    now = now.astimezone(timezone.utc)
    tz = ZoneInfo(cfg["timezone"])
    edition = now.astimezone(tz).date().isoformat()
    state = load_json(site / "state.json", {"events": [], "http": {}, "spend": {}})
    enabled = [s for s in sources if s.get("enabled", True)]
    start = now - timedelta(hours=cfg["window_hours"])

    fetched = fetch_all(enabled, fetcher, state["http"])
    items, report = collect_items(enabled, fetched, now, start)
    ok = sum(1 for r in report["sources"].values() if r["ok"])
    result: dict = {"edition": edition, "sources_ok": ok, "sources_total": len(enabled), "items": len(items), "report": report}
    log_event("collected", edition=edition, sources_ok=ok, sources_total=len(enabled), items=len(items))
    if ok == 0 or (not items and ok < len(enabled)):
        result.update(status="stale", reason="no usable source data; previous edition retained")
        return result

    clusters = cluster(items, cfg["cluster_threshold"])
    annotate(clusters, state["events"])
    for cl in clusters:
        cl["score"] = score(cl, cfg, cl["status"])
    chosen = shortlist(clusters, cfg)
    packets, src_list = build_packets(chosen, cfg)
    head = {"title": cfg["site"]["title"], "edition": edition, "generated_at": now.isoformat(), "window_start": start.isoformat(),
            "window_end": now.isoformat(), "label": label, "warnings": []}
    if ok < len(enabled):
        head["warnings"].append(f"Partial coverage: {len(enabled) - ok} of {len(enabled)} sources unavailable.")

    spent_today = state["spend"].get(edition, 0.0)
    budget = Budget(cfg["llm"], spent_today)
    errs: list[str] = []
    briefing = None
    mode = "dry-run"
    if provider is not None and packets:
        mode, feedback = "llm", None
        for attempt in range(cfg["llm"]["max_attempts"]):
            try:
                writer = llm_write(packets, provider, budget, cfg, cfg["max_words"], feedback)
            except BudgetExceeded as exc:
                errs = [f"budget: {exc}"]
                break
            except Exception as exc:  # noqa: BLE001 - provider/parse failure falls through to fallback
                errs = [f"llm error: {type(exc).__name__}: {str(exc)[:150]}"]
                feedback = errs
                continue
            errs, briefing = verify(writer, packets, src_list, head, cfg)
            log_event("verification", attempt=attempt + 1, errors=errs[:10])
            if briefing:
                break
            feedback = errs
        if briefing is None:
            mode = "evidence-only"
            head["warnings"].append("Automated summary failed verification; evidence-only edition. " + "; ".join(errs[:3])[:300])
    if briefing is None:
        errs, briefing = verify(evidence_only_write(packets, cfg["max_words"]), packets, src_list, head, cfg)
        if briefing is None:
            result.update(status="stale", reason=f"fallback failed verification: {errs[:3]}")
            return result
    briefing["mode"] = mode
    briefing["usage"] = budget.usage()
    briefing["collection"] = {"sources_ok": ok, "sources_total": len(enabled), "items": len(items), "clusters": len(clusters), "quarantined": len(report["quarantined"])}
    result.update(status="published", briefing=briefing, collected_urls=sorted(i.url for i in items), packets=packets, verification_errors=errs)

    if do_publish:
        publish(site, briefing, cfg)
        cited_events = {s["event_id"] for s in sum((sec["items"] for sec in briefing["sections"]), []) + briefing["cyber"] + briefing["disasters"]}
        keys = {(cl.get("prev_key") or cl["id"]) for p in packets if p["event_id"] in cited_events for cl in clusters if cl["id"] == p["cluster_id"]}
        state["events"] = update_history(state["events"], clusters, edition, keys, cfg["state_retention_days"])
        for sid, rep in report["sources"].items():
            if rep["ok"] and rep.get("cache"):
                state["http"][sid] = rep["cache"]
        state["spend"] = {k: v for k, v in state["spend"].items() if k >= (now - timedelta(days=7)).date().isoformat()}
        state["spend"][edition] = round(budget.spent, 6)
        (site / "state.json").write_text(__import__("json").dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    return result
