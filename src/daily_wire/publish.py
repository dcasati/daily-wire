"""Stage G: write editions, OPDS, status and state into the site directory (the only place we ever write)."""
from __future__ import annotations

import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from .epub import render_epub, render_md
from .opds import build_feed

EDITION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_epub(data: bytes) -> list[str]:
    """Structural EPUB checks (no epubcheck dependency; see docs/evaluation.md for the limits)."""
    errs = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ["not a zip"]
    names = z.namelist()
    if not names or names[0] != "mimetype" or z.getinfo("mimetype").compress_type != zipfile.ZIP_STORED or z.read("mimetype") != b"application/epub+zip":
        errs.append("mimetype must be first, stored, and correct")
    for n in names:
        if n.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            try:
                ET.fromstring(z.read(n))
            except ET.ParseError as exc:
                errs.append(f"{n}: not well-formed XML ({exc})")
    try:
        opf = ET.fromstring(z.read("OEBPS/content.opf"))
        ns = {"o": "http://www.idpf.org/2007/opf"}
        hrefs = [i.get("href") for i in opf.findall(".//o:item", ns)]
        errs += [f"manifest item missing: {h}" for h in hrefs if f"OEBPS/{h}" not in names]
        if not any(i.get("properties") == "nav" for i in opf.findall(".//o:item", ns)):
            errs.append("no nav document")
        brief = z.read("OEBPS/brief.xhtml").decode()
        ids = set(re.findall(r'id="([^"]+)"', brief))
        errs += [f"dangling internal link #{a}" for a in set(re.findall(r'href="#([^"]+)"', brief)) if a not in ids]
        if re.search(r'(src|href)="(?!https?://|#|[\w./-]+\.(css|xhtml))', brief):
            errs.append("unexpected resource reference")
        if re.search(r"<(img|script|iframe|object)\b", brief, re.I):
            errs.append("forbidden element")
    except (KeyError, ET.ParseError) as exc:
        errs.append(f"package error: {exc}")
    return errs


def _safe(site: Path, rel: str) -> Path:
    p = (site / rel).resolve()
    if site.resolve() not in p.parents:
        raise ValueError(f"path escapes output directory: {rel}")
    return p


def list_editions(site: Path, recent: int) -> list[dict]:
    eds = []
    for f in sorted((site / "editions").glob("briefing-*.json"), reverse=True):
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
            epub = f.with_suffix(".epub")
            if EDITION_RE.match(b["edition"]) and epub.exists():
                eds.append({"edition": b["edition"], "generated_at": b["generated_at"], "mode": b["mode"], "words": b.get("words"),
                            "label": b.get("label"), "size": epub.stat().st_size})
        except (ValueError, KeyError):
            continue
    return sorted(eds, key=lambda e: e["edition"], reverse=True)[:recent]


def publish(site: Path, briefing: dict, cfg: dict) -> dict:
    if not EDITION_RE.match(briefing["edition"]):
        raise ValueError("bad edition id")
    epub = render_epub(briefing, cfg["timezone"])
    errs = validate_epub(epub)
    if errs:
        raise RuntimeError(f"EPUB validation failed: {errs}")
    ed = briefing["edition"]
    for rel, data in ((f"editions/briefing-{ed}.epub", epub), (f"editions/briefing-{ed}.md", render_md(briefing, cfg["timezone"]).encode()),
                      (f"editions/briefing-{ed}.json", json.dumps(briefing, indent=1, ensure_ascii=False, sort_keys=True).encode())):
        p = _safe(site, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (site / ".nojekyll").write_text("")
    eds = list_editions(site, cfg["site"]["opds_recent"])
    _safe(site, "opds.xml").write_text(build_feed(eds, cfg["site"]["title"], cfg["site"]["base_url"]), encoding="utf-8")
    status = {"last_success": briefing["generated_at"], "edition": ed, "mode": briefing["mode"], "words": briefing.get("words"),
              "usage": briefing.get("usage"), "label": briefing.get("label"), "warnings": briefing.get("warnings", [])}
    _safe(site, "status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
    index = ("<!doctype html><meta charset=utf-8><title>Daily Wire</title><h1>Daily Wire</h1>"
             f'<p>Latest: <a href="editions/briefing-{ed}.epub">{ed}</a> ({briefing["mode"]}). OPDS catalog: <a href="opds.xml">opds.xml</a>. '
             '<a href="status.json">status</a></p>')
    _safe(site, "index.html").write_text(index, encoding="utf-8")
    return status


def health(site: Path, now: datetime, max_age_h: float) -> list[str]:
    """Publication health check: freshness, catalog consistency, EPUB validity of latest edition."""
    probs = []
    try:
        st = json.loads((site / "status.json").read_text())
    except (FileNotFoundError, ValueError):
        return ["status.json missing"]
    age = (now - datetime.fromisoformat(st["last_success"])).total_seconds() / 3600
    if age > max_age_h:
        probs.append(f"latest edition is {age:.1f}h old (limit {max_age_h}h)")
    try:
        feed = ET.parse(site / "opds.xml").getroot()
        hrefs = [l.get("href") for l in feed.iter("{http://www.w3.org/2005/Atom}link") if l.get("rel") == "http://opds-spec.org/acquisition"]
        probs += [f"catalog links missing file {h}" for h in hrefs if not (site / h).exists()]
        if not hrefs:
            probs.append("catalog has no editions")
    except (FileNotFoundError, ET.ParseError):
        probs.append("opds.xml missing or invalid")
    epub = site / "editions" / f"briefing-{st['edition']}.epub"
    if not epub.exists():
        probs.append("latest EPUB missing")
    else:
        probs += validate_epub(epub.read_bytes())
    return probs
