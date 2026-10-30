"""Feed parsing and normalization into Item records. All input is untrusted."""
from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Item, log_event

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)",
    r"disregard (the |all )?(previous|prior|above|system)",
    r"\bsystem prompt\b",
    r"\byou are (now )?(an?|the) (ai|assistant|language model|llm)\b",
    r"\b(new|updated) instructions?:",
    r"</?(system|assistant|evidence)>",
    r"\bas an ai\b",
]
_INJ = re.compile("|".join(INJECTION_PATTERNS), re.I)
_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "ocid", "at_medium", "at_campaign"}
_WIRE = re.compile(r"\((Reuters|AP|AFP|Associated Press)\)|^\s*(Reuters|AP|AFP)\s*[-—:]", re.I)


def looks_injected(text: str) -> bool:
    return bool(_INJ.search(text))


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def canonical_url(url: str) -> str:
    u = urlsplit(url.strip())
    q = urlencode([(k, v) for k, v in parse_qsl(u.query) if k.lower() not in _TRACKING])
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/") or "/", q, ""))


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return None  # ambiguous timestamps are rejected rather than guessed
    return dt.astimezone(timezone.utc)


def parse_feed(body: bytes) -> list[dict]:
    """Parse RSS 2.0 / RDF / Atom. DTD/entity declarations are refused (XML bomb/XXE defence)."""
    if re.search(rb"<!(DOCTYPE|ENTITY)", body, re.I):
        raise ValueError("DTD/entity declarations not allowed")
    root = ET.fromstring(body)
    local = lambda el: el.tag.rsplit("}", 1)[-1]  # noqa: E731
    out = []
    for el in root.iter():
        if local(el) not in ("item", "entry"):
            continue
        rec: dict = {}
        for ch in el:
            n = local(ch)
            if n == "link":
                rec.setdefault("link", ch.get("href") if ch.get("href") else (ch.text or ""))
                if ch.get("href") and ch.get("rel") in (None, "alternate"):
                    rec["link"] = ch.get("href")
            elif n in ("title", "description", "summary", "content", "guid", "id", "pubDate", "published", "updated", "date"):
                rec.setdefault(n, ch.text or "")
        out.append(rec)
    return out


def normalize(rec: dict, source: dict, now: datetime, window_start: datetime) -> tuple[Item | None, str | None]:
    """Return (Item, None) or (None, reject reason)."""
    title = strip_html(rec.get("title", ""))
    link = (rec.get("link") or rec.get("guid") or "").strip()
    if not title or not link.startswith(("http://", "https://")):
        return None, "malformed"
    pub = parse_time(rec.get("pubDate") or rec.get("published") or rec.get("date") or rec.get("updated"))
    if pub is None:
        return None, "bad_timestamp"
    if pub > now + timedelta(hours=1):
        return None, "future_timestamp"
    if pub < window_start:
        return None, "outside_window"
    summary = strip_html(rec.get("description") or rec.get("summary") or rec.get("content") or "")[:1500]
    origin = source.get("origin") or source["id"]
    if source.get("origin") is None:
        m = _WIRE.search(summary) or _WIRE.search(title)
        if m:
            origin = (m.group(1) or m.group(2)).lower().replace("associated press", "ap")
    if source.get("origin"):  # aggregator titles end with " - Publisher"
        title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)
    flags = ["injection"] if looks_injected(f"{title} {summary}") else []
    url = canonical_url(link)
    return Item(
        id=hashlib.sha256(url.encode()).hexdigest()[:16], source_id=source["id"], source=source["name"], origin=origin,
        url=url, title=title, published=pub.isoformat(), summary=summary, region=source.get("region", "global"),
        category=source.get("category", "world"), ingested=now.isoformat(), reliability=float(source.get("reliability", 0.7)),
        official=bool(source.get("official", False)), flags=flags,
    ), None


def collect_items(sources: list[dict], fetched: dict, now: datetime, window_start: datetime) -> tuple[list[Item], dict]:
    """Normalize all fetched feeds; returns (deduplicated items, per-source report)."""
    items: dict[str, Item] = {}
    report: dict[str, dict] = {}
    for src in sources:
        res = fetched.get(src["id"])
        rep = report[src["id"]] = {"ok": False, "items": 0, "rejected": {}}
        if isinstance(res, Exception) or res is None:
            rep["error"] = str(res)[:200]
            log_event("source_failed", source=src["id"], error=rep["error"])
            continue
        body, cache = res
        rep["cache"], rep["ok"] = cache, True
        if body is None:
            rep["not_modified"] = True
            continue
        try:
            records = parse_feed(body)
        except (ET.ParseError, ValueError) as exc:
            rep.update(ok=False, error=f"parse: {exc}"[:200])
            log_event("source_failed", source=src["id"], error=rep["error"])
            continue
        for rec in records:
            it, why = normalize(rec, src, now, window_start)
            if it is None:
                rep["rejected"][why] = rep["rejected"].get(why, 0) + 1
            elif it.id not in items:  # exact-URL duplicate
                items[it.id] = it
                rep["items"] += 1
    quarantined = [i for i in items.values() if "injection" in i.flags]
    for i in quarantined:
        log_event("quarantined_item", id=i.id, source=i.source_id)
    return [i for i in items.values() if "injection" not in i.flags], {"sources": report, "quarantined": [i.id for i in quarantined]}
