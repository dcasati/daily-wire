"""OPDS 1.2 (Atom) acquisition catalog for KOReader."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape

NS = 'xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/" xmlns:opds="http://opds-spec.org/2010/catalog"'


def build_feed(editions: list[dict], title: str, base_url: str = "", now: datetime | None = None) -> str:
    """editions: dicts with edition, generated_at, mode, words, label, size. Newest first."""
    now = now or datetime.now(timezone.utc)
    link = lambda path: (base_url.rstrip("/") + "/" + path) if base_url else path  # noqa: E731
    out = ['<?xml version="1.0" encoding="utf-8"?>', f"<feed {NS}>", "<id>urn:daily-wire:catalog</id>", f"<title>{escape(title)}</title>",
           f"<updated>{(editions[0]['generated_at'] if editions else now.isoformat())}</updated>", "<author><name>Daily Wire (automated)</name></author>",
           f'<link rel="self" href="{escape(link("opds.xml"), quote=True)}" type="application/atom+xml;profile=opds-catalog;kind=acquisition"/>',
           f'<link rel="start" href="{escape(link("opds.xml"), quote=True)}" type="application/atom+xml;profile=opds-catalog;kind=acquisition"/>']
    for e in editions:
        label = " [TEST]" if e.get("label") else ""
        href = escape(link(f"editions/briefing-{e['edition']}.epub"), quote=True)
        out.append(f"<entry><id>urn:daily-wire:{e['edition']}{':test' if e.get('label') else ''}</id><title>{escape(title)} {e['edition']}{label}</title>"
                   f"<updated>{e['generated_at']}</updated><dc:language>en</dc:language><dc:issued>{e['edition']}</dc:issued>"
                   f"<summary>{escape(str(e.get('mode')))} edition, {e.get('words', '?')} words</summary>"
                   f'<link rel="http://opds-spec.org/acquisition" href="{href}" type="application/epub+zip" length="{e.get("size", 0)}"/></entry>')
    out.append("</feed>")
    return "\n".join(out) + "\n"
