"""Stage F: deterministic verification. No LLM is used to judge LLM output."""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .normalize import looks_injected
from .summarize import build_briefing, editorial_words

HEDGE = re.compile(r"\b(according to|reported|reportedly|said|says|claimed?|alleged(ly)?|unconfirmed|officials? (said|say)|state media)\b", re.I)
CONTESTED = re.compile(r"\b(differ|differs|conflict\w*|contradict\w*|disput\w*|unclear|discrepan\w*)\b", re.I)
LOADED = {"killed", "destroyed", "invaded", "captured", "seized", "struck", "bombed", "assassinated", "annihilated", "massacre",
          "genocide", "atrocity", "terrorist", "declared", "surrendered", "resigned", "overthrown"}
KINDS = {"observed", "attributed", "assessment"}


def _words(s: str) -> set[str]:
    """Words plus the parts of hyphenated compounds ("Guinea-Bissau" also yields "guinea" and "bissau")."""
    whole = re.findall(r"[a-z0-9][a-z0-9\-]*", s.lower())
    return set(whole) | {part for w in whole for part in w.split("-") if part}


def _corpus(entries: list[dict]) -> str:
    return " ".join(f"{e['title']} {e['snippet']} {e['source']}" for e in entries).lower()


def check_grounding(text: str, corpus: str) -> list[str]:
    errs = []
    cw = _words(corpus)
    for num in re.findall(r"\d[\d,.]*\d|\d", text):
        if num.strip(",.") not in corpus:
            errs.append(f"number '{num}' not in cited evidence")
    stripped = re.sub(r"(^|[.!?]\s+|:\s+)\S+", r"\1", text)  # ignore sentence-initial words
    for noun in re.findall(r"\b[A-Z][a-z]{2,}\b", stripped):
        if noun.lower() not in cw and noun.lower()[:5] not in {w[:5] for w in cw}:
            errs.append(f"name '{noun}' not in cited evidence")
    for w in _words(text) & LOADED:
        if w not in cw:
            errs.append(f"assertive term '{w}' not in cited evidence")
    content = [w for w in _words(text) if len(w) > 3]
    prefixes = {w[:5] for w in cw}
    if content and sum(w[:5] in prefixes for w in content) / len(content) < 0.5:
        errs.append("less than half of content words appear in cited evidence")
    return errs


def verify(writer: dict, packets: list[dict], sources: list[dict], head: dict, cfg: dict) -> tuple[list[str], dict | None]:
    errs: list[str] = []
    by_event = {p["event_id"]: p for p in packets}
    valid_refs = {s["n"] for s in sources}
    all_urls = {s["url"] for s in sources}
    if not isinstance(writer, dict) or not isinstance(writer.get("bluf"), str) or not isinstance(writer.get("statements"), list):
        return ["schema: need bluf (str) and statements (list)"], None
    seen_events: set[str] = set()
    for s in writer["statements"]:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or not isinstance(s.get("refs"), list):
            return ["schema: malformed statement"], None
        eid = s.get("event_id")
        p = by_event.get(eid)
        if p is None:
            errs.append(f"{eid}: unknown event (not in evidence)")
            continue
        if eid in seen_events:
            errs.append(f"{eid}: repeated event")
        seen_events.add(eid)
        if s.get("kind") not in KINDS:
            errs.append(f"{eid}: invalid kind")
        refs = s["refs"]
        if not refs or not all(isinstance(r, int) and not isinstance(r, bool) for r in refs):
            errs.append(f"{eid}: missing/invalid citations")
            continue
        own = {e["n"] for e in p["evidence"]}
        for r in refs:
            if r not in valid_refs:
                errs.append(f"{eid}: citation [{r}] does not resolve to a collected source")
            elif r not in own:
                errs.append(f"{eid}: citation [{r}] belongs to a different event (misattribution)")
        text = s["text"]
        errs += [f"{eid}: {e}" for e in check_grounding(text, _corpus([e for e in p["evidence"] if e["n"] in refs]))]
        if p["confidence"] == "low" and not (s.get("kind") in ("attributed", "assessment") and HEDGE.search(text)):
            errs.append(f"{eid}: weakly corroborated claim must be attributed")
        if p["disagreements"] and not CONTESTED.search(text):
            errs.append(f"{eid}: known disagreement in evidence not disclosed")
        if looks_injected(text) or any(u not in all_urls for u in re.findall(r"https?://\S+", text)):
            errs.append(f"{eid}: injected instruction or unknown URL in text")
    bluf = writer["bluf"]
    if len(re.findall(r"[.!?](\s|$)", bluf)) > 3:
        errs.append("bluf exceeds three sentences")
    allcorpus = " ".join(_corpus(p["evidence"]) for p in packets)
    errs += [f"bluf: {e}" for e in check_grounding(bluf, allcorpus) if "content words" not in e]
    if looks_injected(bluf):
        errs.append("bluf: injected instruction")
    for w in writer.get("watch", []):
        if not isinstance(w, dict) or not w.get("refs") or not all(r in valid_refs for r in w["refs"]):
            errs.append("watch: invalid or missing citations")
        else:
            errs += [f"watch: {e}" for e in check_grounding(f"{w['indicator']}. {w['significance']}", allcorpus) if "content words" not in e and "assertive" not in e]
    if len(writer.get("watch", [])) > 3:
        errs.append("more than three watch items")
    tz = ZoneInfo(cfg["timezone"])
    gen = datetime.fromisoformat(head["generated_at"])
    if head["edition"] != gen.astimezone(tz).date().isoformat():
        errs.append("edition date does not match publication date")
    if not head["window_start"] < head["window_end"] <= head["generated_at"]:
        errs.append("coverage window inconsistent")
    if errs:
        return errs, None
    briefing = build_briefing(writer, packets, sources, head)
    words = editorial_words(briefing)
    briefing["words"] = words
    if words > cfg["max_words"]:
        errs.append(f"word count {words} exceeds {cfg['max_words']}")
    return errs, (None if errs else briefing)
