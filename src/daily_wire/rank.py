"""Stage C: explainable significance scoring, separated from confidence."""
from __future__ import annotations

import re
from collections import Counter

from .models import SECTIONS, Item

CYBER, DISASTER = "Cyber and Infrastructure", "Significant Disasters"


def _has(text: str, kw: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(kw)}", text, re.I) is not None


def item_section(item: Item, cfg: dict) -> str:
    if item.category == "cyber":
        return CYBER
    if item.category == "disaster":
        return DISASTER
    text = f"{item.title} {item.summary}"
    if item.region in SECTIONS:
        return item.region
    for sec, kws in cfg["region_keywords"].items():
        if any(_has(text, k) for k in kws):
            return sec
    return "Other Regions"


def cluster_section(cl: dict, cfg: dict) -> str:
    counts = Counter(item_section(i, cfg) for i in cl["items"])
    order = SECTIONS + [CYBER, DISASTER]
    return sorted(counts, key=lambda s: (-counts[s], order.index(s)))[0]


def independent_origins(cl: dict) -> int:
    return len({i.origin for i in cl["items"]})


def confidence(cl: dict) -> str:
    """Confidence in the facts (not importance). Syndicated copies share an origin and do not corroborate."""
    n = independent_origins(cl)
    rel = max(i.reliability for i in cl["items"])
    if n >= 2 and rel >= 0.8:
        return "high"
    if n >= 2 or any(i.official for i in cl["items"]):
        return "moderate"
    return "low"


def score(cl: dict, cfg: dict, novelty: str) -> dict:
    """Return {'total': float, 'parts': {...}}. Every part is deterministic and inspectable."""
    w = cfg["weights"]
    text = " ".join(f"{i.title} {i.summary}" for i in cl["items"])
    title_text = " ".join(i.title for i in cl["items"])
    terms = {t: v for t, v in cfg["impact_terms"].items() if _has(text, t)}
    impact = min(sum(terms.values()), w["impact_cap"])
    nums = [float(n.replace(",", "")) for n in re.findall(r"\b\d[\d,]*\.?\d*\b", title_text) if n.replace(",", "").replace(".", "", 1).isdigit()]
    mag = re.search(r"\bM\s?(\d\.\d)\b|magnitude (\d\.\d)", title_text)
    scale = w["scale"] if (any(n >= cfg["scale_numbers_min"] for n in nums) or (mag and float(mag.group(1) or mag.group(2)) >= 6.5)) else 0.0
    cat = max(cfg["category_weight"].get(i.category, 1.0) for i in cl["items"]) * w["category"] * 0.5
    quality = (sum(i.reliability for i in cl["items"]) / len(cl["items"])) * w["source_quality"]
    corr = (min(independent_origins(cl), 3) - 1) * w["corroboration"]
    nov = {"new": w["novelty"], "updated": w["novelty"] / 2, "unchanged": 0.0}[novelty]
    canada = w["canada"] if any(_has(text, k) for k in cfg["canada_keywords"]) else 0.0
    parts = {"impact": impact, "scale": scale, "category": cat, "source_quality": quality, "corroboration": corr, "novelty": nov, "canada": canada}
    return {"total": round(sum(parts.values()), 3), "parts": {k: round(v, 3) for k, v in parts.items()}, "terms": sorted(terms)}


def shortlist(clusters: list[dict], cfg: dict) -> list[dict]:
    """Deterministic pre-LLM filter. Unchanged events never qualify; impact terms are required."""
    keep = []
    for cl in clusters:
        s = cl["score"]
        if cl["status"] == "unchanged" or not s["terms"] and s["parts"]["scale"] == 0:
            continue
        if s["total"] >= cfg["min_score"]:
            keep.append(cl)
    keep.sort(key=lambda c: (-c["score"]["total"], c["id"]))
    return keep[: cfg["max_events"]]
