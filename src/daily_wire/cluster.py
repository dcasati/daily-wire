"""Stage B: cluster related items into events (title-token Jaccard, union-find)."""
from __future__ import annotations

import hashlib
import re

from .models import Item

STOP = set("the a an of in on at to for and or with by from as is are was were be has have had after over amid says say said new "
           "its it this that into than their his her they who will would could may might up out not but more".split())


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "al", "es", "s"):
        if len(w) > 5 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text: str) -> frozenset[str]:
    return frozenset(_stem(w) for w in re.findall(r"[a-z0-9][a-z0-9.\-]*", text.lower()) if w not in STOP and len(w) > 1)


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def cluster(items: list[Item], threshold: float = 0.4) -> list[dict]:
    items = sorted(items, key=lambda i: (i.published, i.id))
    toks = [tokens(i.title) for i in items]
    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(items)):
        for j in range(i):
            if jaccard(toks[i], toks[j]) >= threshold:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for idx in groups.values():
        members = [items[k] for k in idx]
        out.append({
            "id": hashlib.sha256(members[0].id.encode()).hexdigest()[:12],
            "items": members,
            "tokens": sorted(frozenset().union(*(toks[k] for k in idx))),
            "origins": sorted({m.origin for m in members}),
        })
    return sorted(out, key=lambda c: c["id"])
