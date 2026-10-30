"""EPUB 3 (with NCX for older readers) and Markdown rendering. Stdlib only, no external resources."""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

CSS = """body{font-family:serif;line-height:1.4;margin:0 .5em}h1{font-size:1.5em;margin:.2em 0}
h2{font-size:1.15em;border-bottom:1px solid #000;margin-top:1.2em}p,li{margin:.4em 0}
.meta{font-size:.85em}.warn{border:1px solid #000;padding:.4em;font-weight:bold}a{color:inherit}sup a{text-decoration:none}"""


def _safe_url(u: str) -> str:
    return escape(u, quote=True) if re.match(r"https?://", u) else "#"


def _refs_html(refs: list[int]) -> str:
    return "".join(f'<sup><a href="#s{n}">[{n}]</a></sup>' for n in refs)


def _stmt(s: dict) -> str:
    kind = "" if s["kind"] == "observed" else f' <i>({escape(s["kind"])})</i>'
    return f"<li>{escape(s['text'])}{kind} {_refs_html(s['refs'])}</li>"


def _local(b: dict, key: str, tz: str) -> str:
    return datetime.fromisoformat(b[key]).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M %Z")


def body_html(b: dict, tz: str) -> str:
    h = [f"<h1>{escape(b['title'])}</h1>"]
    if b.get("label"):
        h.append(f'<p class="warn">{escape(b["label"])}</p>')
    for w in b.get("warnings", []):
        h.append(f'<p class="warn">{escape(w)}</p>')
    h.append(f'<p class="meta">Edition {escape(b["edition"])} &#183; published {escape(_local(b, "generated_at", tz))} &#183; '
             f'cutoff {escape(_local(b, "window_end", tz))} &#183; window from {escape(_local(b, "window_start", tz))} &#183; mode: {escape(b["mode"])}</p>')
    h.append(f'<h2 id="bluf">BLUF</h2><p>{escape(b["bluf"])}</p>')
    h.append('<h2 id="regional">Regional Developments</h2>')
    shown = False
    for sec in b["sections"]:
        if sec["items"]:
            shown = True
            h.append(f"<h3>{escape(sec['name'])}</h3><ul>{''.join(_stmt(s) for s in sec['items'])}</ul>")
    if not shown:
        h.append("<p>No significant regional developments met the threshold.</p>")
    for anchor, title, key in (("cyber", "Cyber and Infrastructure", "cyber"), ("disasters", "Significant Disasters", "disasters")):
        if b[key]:
            h.append(f'<h2 id="{anchor}">{title}</h2><ul>{"".join(_stmt(s) for s in b[key])}</ul>')
    h.append(f'<h2 id="changes">Changes Since Previous Brief</h2><p>{escape(b["changes_summary"])}</p>')
    if b["changes"]:
        h.append("<ul>" + "".join(f"<li>{escape(c['text'])} {_refs_html(c['refs'])}</li>" for c in b["changes"]) + "</ul>")
    if b["watch"]:
        h.append('<h2 id="watch">Watch Items &#8212; Next 24&#8211;72 Hours</h2><ul>' + "".join(
            f"<li><b>{escape(w['indicator'])}</b> {escape(w['significance'])} {_refs_html(w['refs'])}</li>" for w in b["watch"]) + "</ul>")
    h.append('<h2 id="sources">Sources</h2><ol>')
    for s in b["sources"]:
        h.append(f'<li id="s{s["n"]}">{escape(s["name"])}: <a href="{_safe_url(s["url"])}">{escape(s["title"])}</a> ({escape(s["published"][:16])}Z)</li>')
    h.append("</ol>")
    h.append(f'<p class="meta">{b["words"]} editorial words. Automated compilation from cited sources; not verified independently of them.</p>')
    return "\n".join(h)


def render_epub(b: dict, tz: str = "America/Edmonton") -> bytes:
    uid = f"urn:daily-wire:{b['edition']}" + (":test" if b.get("label") else "")
    title = f"{b['title']} {b['edition']}"
    xh = lambda inner: ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" '  # noqa: E731
                        'xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en"><head><meta charset="utf-8"/>'
                        f'<title>{escape(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head><body>{inner}</body></html>')
    nav_items = [("bluf", "BLUF"), ("regional", "Regional Developments")] + [(a, t) for a, t, k in
                 (("cyber", "Cyber and Infrastructure", "cyber"), ("disasters", "Significant Disasters", "disasters")) if b[k]]
    nav_items += [("changes", "Changes Since Previous Brief")] + ([("watch", "Watch Items")] if b["watch"] else []) + [("sources", "Sources")]
    nav = xh('<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>' + "".join(f'<li><a href="brief.xhtml#{a}">{escape(t)}</a></li>' for a, t in nav_items) + "</ol></nav>")
    ncx = ('<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head>'
           f'<meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{escape(title)}</text></docTitle><navMap>'
           + "".join(f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{escape(t)}</text></navLabel><content src="brief.xhtml#{a}"/></navPoint>'
                     for i, (a, t) in enumerate(nav_items, 1)) + "</navMap></ncx>")
    modified = datetime.fromisoformat(b["generated_at"]).strftime("%Y-%m-%dT%H:%M:%SZ")
    opf = ('<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="en">'
           f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">{uid}</dc:identifier><dc:title>{escape(title)}</dc:title>'
           f'<dc:language>en</dc:language><dc:creator>Daily Wire (automated)</dc:creator><dc:date>{b["edition"]}</dc:date>'
           f'<meta property="dcterms:modified">{modified}</meta></metadata><manifest>'
           '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
           '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
           '<item id="brief" href="brief.xhtml" media-type="application/xhtml+xml"/>'
           '<item id="css" href="style.css" media-type="text/css"/></manifest>'
           '<spine toc="ncx"><itemref idref="brief"/><itemref idref="nav" linear="no"/></spine></package>')
    container = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                 '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype", (1980, 1, 1, 0, 0, 0)), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, data in (("META-INF/container.xml", container), ("OEBPS/content.opf", opf), ("OEBPS/nav.xhtml", nav),
                           ("OEBPS/toc.ncx", ncx), ("OEBPS/brief.xhtml", xh(body_html(b, tz))), ("OEBPS/style.css", CSS)):
            zi = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data.encode("utf-8"))
    return buf.getvalue()


def render_md(b: dict, tz: str = "America/Edmonton") -> str:
    cite = lambda refs: " " + "".join(f"[[{n}]](#s{n})" for n in refs)  # noqa: E731
    out = [f"# {b['title']}", ""]
    if b.get("label"):
        out += [f"**{b['label']}**", ""]
    out += [f"Edition {b['edition']} | published {_local(b, 'generated_at', tz)} | cutoff {_local(b, 'window_end', tz)} | mode: {b['mode']}", "",
            f"## BLUF\n{b['bluf']}", "", "## Regional Developments"]
    for sec in b["sections"]:
        if sec["items"]:
            out += [f"### {sec['name']}"] + [f"- {s['text']} ({s['kind']}){cite(s['refs'])}" for s in sec["items"]] + [""]
    for t, k in (("Cyber and Infrastructure", "cyber"), ("Significant Disasters", "disasters")):
        if b[k]:
            out += [f"## {t}"] + [f"- {s['text']} ({s['kind']}){cite(s['refs'])}" for s in b[k]] + [""]
    out += ["## Changes Since Previous Brief", b["changes_summary"]] + [f"- {c['text']}{cite(c['refs'])}" for c in b["changes"]] + [""]
    if b["watch"]:
        out += ["## Watch Items — Next 24–72 Hours"] + [f"- **{w['indicator']}** {w['significance']}{cite(w['refs'])}" for w in b["watch"]] + [""]
    out += ["## Sources"] + [f"{s['n']}. <a id=\"s{s['n']}\"></a>{s['name']}: [{s['title']}]({s['url']}) ({s['published'][:16]}Z)" for s in b["sources"]]
    return "\n".join(out) + "\n"
