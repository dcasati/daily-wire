"""Atom 1.0 feed of recent editions for ordinary feed readers (full text in each entry)."""
from __future__ import annotations

from html import escape

NS = "http://www.w3.org/2005/Atom"


def _cite(refs: list[int]) -> str:
    return " " + "".join(f"[{n}]" for n in refs) if refs else ""


def render_html(b: dict) -> str:
    li = lambda s: f"<li>{escape(s['text'])} <i>({escape(s['kind'])})</i>{_cite(s['refs'])}</li>"  # noqa: E731
    out = [f"<p><b>BLUF:</b> {escape(b['bluf'])}</p>"]
    if b.get("label"):
        out.insert(0, f"<p><b>{escape(b['label'])}</b></p>")
    for sec in b["sections"]:
        if sec["items"]:
            out += [f"<h3>{escape(sec['name'])}</h3><ul>", *map(li, sec["items"]), "</ul>"]
    for title, key in (("Cyber and Infrastructure", "cyber"), ("Significant Disasters", "disasters")):
        if b[key]:
            out += [f"<h3>{title}</h3><ul>", *map(li, b[key]), "</ul>"]
    out.append(f"<h3>Changes since previous brief</h3><p>{escape(b['changes_summary'])}</p>")
    if b["changes"]:
        out += ["<ul>", *(f"<li>{escape(c['text'])}{_cite(c['refs'])}</li>" for c in b["changes"]), "</ul>"]
    if b["watch"]:
        out += ["<h3>Watch items (next 24-72 hours)</h3><ul>"]
        out += [f"<li><b>{escape(w['indicator'])}</b> {escape(w['significance'])}{_cite(w['refs'])}</li>" for w in b["watch"]] + ["</ul>"]
    out.append("<h3>Sources</h3><ol>")
    for s in b["sources"]:
        url = s["url"] if s["url"].startswith(("http://", "https://")) else ""
        label = escape(f"{s['name']}: {s['title']}")
        out.append(f'<li value="{int(s["n"])}"><a href="{escape(url, quote=True)}">{label}</a></li>' if url else f"<li value=\"{int(s['n'])}\">{label}</li>")
    out.append("</ol>")
    return "\n".join(out)


def build_atom(briefings: list[dict], title: str, base_url: str = "") -> str:
    """briefings: full edition dicts, newest first."""
    link = lambda path: (base_url.rstrip("/") + "/" + path) if base_url else path  # noqa: E731
    self_href = escape(link("feed.xml"), quote=True)
    out = ['<?xml version="1.0" encoding="utf-8"?>', f'<feed xmlns="{NS}">', "<id>urn:daily-wire:feed</id>", f"<title>{escape(title)}</title>",
           f"<updated>{briefings[0]['generated_at'] if briefings else '1970-01-01T00:00:00+00:00'}</updated>",
           "<author><name>Daily Wire (automated)</name></author>",
           f'<link rel="self" type="application/atom+xml" href="{self_href}"/>', f'<link rel="alternate" type="text/html" href="{escape(link(""), quote=True)}"/>']
    for b in briefings:
        label = " [TEST]" if b.get("label") else ""
        eid = f"urn:daily-wire:{b['edition']}{':test' if b.get('label') else ''}"
        epub = escape(link(f"editions/briefing-{b['edition']}.epub"), quote=True)
        out.append(f"<entry><id>{eid}</id><title>{escape(title)} {b['edition']}{label}</title><updated>{b['generated_at']}</updated>"
                   f'<link rel="alternate" type="application/epub+zip" href="{epub}"/>'
                   f'<summary>{escape(b["bluf"])}</summary><content type="html">{escape(render_html(b))}</content></entry>')
    out.append("</feed>")
    return "\n".join(out) + "\n"
