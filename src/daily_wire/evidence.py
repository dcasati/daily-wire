"""Stage D: compact evidence packets. Only retrieved evidence enters the LLM prompt."""
from __future__ import annotations

import re

from .rank import cluster_section, confidence, independent_origins

MAX_ITEMS_PER_EVENT = 3
SNIPPET = 280


def _figures(title: str) -> set[str]:
    return {n for n in re.findall(r"\b\d[\d,]*\b", title) if int(n.replace(",", "")) >= 2}


def disagreements(items) -> list[str]:
    by_origin: dict[str, set[str]] = {}
    for i in items:
        f = _figures(i.title)
        if f:
            by_origin.setdefault(i.origin, set()).update(f)
    if len({frozenset(v) for v in by_origin.values()}) > 1:
        return ["Reported figures differ: " + "; ".join(f"{', '.join(sorted(v))} ({o})" for o, v in sorted(by_origin.items()))]
    return []


def build_packets(shortlisted: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Return (packets, numbered sources). Source numbers are the only citation handles the writer may use."""
    sources: list[dict] = []
    packets = []
    for k, cl in enumerate(shortlisted, 1):
        chosen, seen = [], set()
        for it in sorted(cl["items"], key=lambda i: (-i.reliability, i.published, i.id)):
            if it.origin not in seen and len(chosen) < MAX_ITEMS_PER_EVENT:
                chosen.append(it)
                seen.add(it.origin)
        entries = []
        for it in chosen:
            n = len(sources) + 1
            sources.append({"n": n, "id": it.id, "name": it.source, "url": it.url, "title": it.title, "published": it.published})
            entries.append({"n": n, "source": it.source, "origin": it.origin, "published": it.published, "title": it.title, "snippet": it.summary[:SNIPPET]})
        gaps = ["Event time not stated in feed; publication time shown only."]
        if independent_origins(cl) < 2:
            gaps.append("Single independent origin; not corroborated.")
        packets.append({
            "event_id": f"E{k}", "cluster_id": cl["id"], "section": cluster_section(cl, cfg), "status": cl["status"],
            "confidence": confidence(cl), "score": cl["score"]["total"], "independent_origins": independent_origins(cl),
            "prev_title": cl.get("prev_title"), "evidence": entries, "disagreements": disagreements(cl["items"]), "gaps": gaps,
        })
    return packets, sources
