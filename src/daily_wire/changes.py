"""Change detection against persisted event history."""
from __future__ import annotations

from .cluster import jaccard

MATCH = 0.35


def annotate(clusters: list[dict], prev_events: list[dict]) -> None:
    """Set cluster['status'] to new / updated / unchanged and cluster['prev_key'] when matched."""
    for cl in clusters:
        toks = frozenset(cl["tokens"])
        best, best_s = None, 0.0
        for ev in prev_events:
            s = jaccard(toks, frozenset(ev["tokens"]))
            if s > best_s:
                best, best_s = ev, s
        if best is None or best_s < MATCH:
            cl["status"], cl["prev_key"] = "new", None
            continue
        cl["prev_key"] = best["key"]
        if "last_published" not in best:  # seen but never published: still news to the reader
            cl["status"] = "new"
            continue
        fresh = [i for i in cl["items"] if i.id not in set(best["item_ids"])]
        cl["status"] = "updated" if fresh else "unchanged"
        cl["new_item_ids"] = [i.id for i in fresh]
        cl["prev_title"] = best["title"]


def update_history(prev_events: list[dict], clusters: list[dict], edition: str, published_keys: set[str], retention_days: int) -> list[dict]:
    """Merge this run's clusters into history. Only items seen are recorded (not necessarily published)."""
    by_key = {e["key"]: e for e in prev_events}
    for cl in clusters:
        key = cl.get("prev_key") or cl["id"]
        ev = by_key.setdefault(key, {"key": key, "first_seen": edition, "item_ids": [], "title": cl["items"][0].title})
        ev["tokens"] = sorted(set(ev.get("tokens", [])) | set(cl["tokens"]))
        ev["item_ids"] = sorted(set(ev["item_ids"]) | {i.id for i in cl["items"]})
        ev["last_seen"] = edition
        if key in published_keys:
            ev["last_published"] = edition
    cutoff = _minus_days(edition, retention_days)
    return [e for e in by_key.values() if e["last_seen"] >= cutoff]


def _minus_days(edition: str, days: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(edition) - timedelta(days=days)).isoformat()
