from __future__ import annotations

import json
import zipfile
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from daily_wire.atomfeed import build_atom
from daily_wire.changes import annotate, update_history
from daily_wire.cluster import cluster, tokens
from daily_wire.epub import render_epub
from daily_wire.evaluate import adversarial_cases, evaluate
from daily_wire.fetch import FetchError, FixtureFetcher, check_url
from daily_wire.normalize import canonical_url, collect_items, normalize, parse_feed, parse_time
from daily_wire.opds import build_feed
from daily_wire.pipeline import run
from daily_wire.publish import health, publish, validate_epub, _safe
from daily_wire.rank import confidence, score
from daily_wire.summarize import Budget, BudgetExceeded

ROOT = Path(__file__).parent.parent
FX = ROOT / "tests" / "fixtures"
CFG = yaml.safe_load((ROOT / "config" / "briefing.yaml").read_text())
SOURCES = yaml.safe_load((FX / "sources.yaml").read_text())["sources"]
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
START = NOW - timedelta(hours=24)
SRC = {"id": "s", "name": "S", "category": "world", "region": "global", "reliability": 0.8}


def rec(**kw):
    return {"title": "Drones strike port", "link": "https://x.test/a?utm_source=z#frag", "pubDate": "Thu, 29 Oct 2026 22:30:00 GMT", **kw}


# ---- normalization & time windows
def test_normalize_ok_and_canonical_url():
    it, why = normalize(rec(), SRC, NOW, START)
    assert why is None and it.url == "https://x.test/a" and it.published.startswith("2026-10-29T22:30")


@pytest.mark.parametrize("kw,reason", [
    ({"title": ""}, "malformed"), ({"link": "javascript:alert(1)"}, "malformed"),
    ({"pubDate": "garbage"}, "bad_timestamp"), ({"pubDate": "2026-10-29T10:00:00"}, "bad_timestamp"),  # naive time rejected
    ({"pubDate": "Sat, 31 Oct 2026 20:00:00 GMT"}, "future_timestamp"), ({"pubDate": "Mon, 26 Oct 2026 09:00:00 GMT"}, "outside_window"),
])
def test_normalize_rejects(kw, reason):
    assert normalize(rec(**kw), SRC, NOW, START)[1] == reason


def test_parse_time_variants():
    assert parse_time("2026-10-30T05:00:00-06:00") == datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
    assert parse_time(None) is None


def test_xml_entity_bomb_refused():
    with pytest.raises(ValueError):
        parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel/></rss>')


def test_parse_atom_and_rss():
    assert parse_feed((FX / "usgs_sig.xml").read_bytes())[0]["link"].startswith("https://")
    assert len(parse_feed((FX / "bbc_world.xml").read_bytes())) == 6


def test_wire_origin_detection():
    it, _ = normalize(rec(description="Reuters - something happened"), SRC, NOW, START)
    assert it.origin == "reuters"


def test_collect_partial_failure_and_quarantine():
    fetched = FixtureFetcher(FX)
    from daily_wire.fetch import fetch_all
    items, rep = collect_items(SOURCES[:8], fetch_all(SOURCES[:8], fetched, {}), NOW, START)
    assert rep["sources"]["broken_feed"]["ok"] is False and rep["sources"]["bbc_world"]["ok"]
    assert len(rep["quarantined"]) == 1 and all("injection" not in i.flags for i in items)
    assert rep["sources"]["bbc_world"]["rejected"] == {"future_timestamp": 1, "outside_window": 1, "bad_timestamp": 1}


# ---- SSRF
@pytest.mark.parametrize("url", ["http://example.com/x", "https://user:pw@example.com/", "https://127.0.0.1/", "https://localhost/",
                                 "https://169.254.169.254/latest", "https://[::1]/", "https://example.com:8443/", "file:///etc/passwd"])
def test_check_url_blocks_unsafe(url):
    with pytest.raises(FetchError):
        check_url(url)


# ---- clustering
def _items(titles):
    out = []
    for i, (t, src) in enumerate(titles):
        it, _ = normalize(rec(title=t, link=f"https://x.test/{i}", description=""), {**SRC, "id": src, "name": src}, NOW, START)
        out.append(it)
    return out


def test_cluster_merges_variants_but_keeps_distinct():
    its = _items([("Naval drones strike Baltic port facility, officials say", "a"), ("Naval drones hit Baltic port facility, officials report", "b"),
                  ("Earthquake of magnitude 7.1 hits Pacific coast", "c")])
    cl = cluster(its)
    assert sorted(len(c["items"]) for c in cl) == [1, 2]


def test_syndicated_copies_do_not_corroborate():
    its = _items([("Naval drones strike Baltic port facility, officials say", "a"), ("Naval drones strike Baltic port facility, officials say today", "b")])
    for i in its:
        i.origin = "reuters"
    cl = cluster(its)[0]
    assert len(cl["items"]) == 2 and confidence(cl) == "low"


def test_tokens_stemming():
    assert tokens("Flooding kills") & tokens("flood killed") 


# ---- ranking
def test_score_is_explainable_and_separates_confidence():
    cl = cluster(_items([("Missile strike kills 40 near border", "a")]))[0]
    s = score(cl, CFG, "new")
    assert set(s["parts"]) == {"impact", "scale", "category", "source_quality", "corroboration", "novelty", "canada"}
    assert s["total"] == pytest.approx(sum(s["parts"].values()), abs=0.01) and confidence(cl) == "low"
    assert score(cl, CFG, "unchanged")["total"] < s["total"]


# ---- change detection
def test_change_detection_cycle():
    cl = cluster(_items([("Naval drones strike Baltic port facility", "a")]))
    annotate(cl, [])
    assert cl[0]["status"] == "new"
    hist = update_history([], cl, "2026-10-29", {cl[0]["id"]}, 14)
    cl2 = cluster(_items([("Naval drones strike Baltic port facility", "a")]))
    annotate(cl2, hist)
    assert cl2[0]["status"] == "unchanged"
    cl3 = cluster(_items([("Naval drones strike Baltic port facility", "a"), ("Naval drones strike Baltic port facility again", "b")]))
    annotate(cl3, hist)
    assert cl3[0]["status"] == "updated"


def test_seen_but_unpublished_stays_new():
    cl = cluster(_items([("Naval drones strike Baltic port facility", "a")]))
    hist = update_history([], cl, "2026-10-29", set(), 14)
    annotate(cl, hist)
    assert cl[0]["status"] == "new"


# ---- budget
def test_budget_hard_stop():
    b = Budget({"max_daily_usd": 0.01, "price_in_per_mtok": 1.0, "price_out_per_mtok": 1.0}, spent_today=0.0099)
    with pytest.raises(BudgetExceeded):
        b.authorize(1000, 1000)


# ---- integration
@pytest.fixture(scope="module")
def result(tmp_path_factory):
    site = tmp_path_factory.mktemp("site")
    return run(CFG, SOURCES, FixtureFetcher(FX), NOW, site, None, "TEST"), site


def test_pipeline_partial_failure_publishes(result):
    r, site = result
    b = r["briefing"]
    assert r["status"] == "published" and r["sources_ok"] == 7 and any("Partial coverage" in w for w in b["warnings"])
    assert 0 < b["words"] <= 600 and b["label"] == "TEST"
    assert (site / "editions" / "briefing-2026-10-30.epub").exists() and (site / "state.json").exists()


def test_noise_excluded_and_distinct_events_not_collapsed(result):
    r, _ = result
    titles = " ".join(s["title"] for s in r["briefing"]["sources"])
    assert "chef" not in titles and "Parliament" not in titles and "Ransomware" not in titles
    assert len(r["briefing"]["events"]) == 6


def test_contradictory_reports_disclosed(result):
    r, _ = result
    flood = next(s for sec in r["briefing"]["sections"] for s in sec["items"] if "flood" in s["text"].lower())
    assert "differ" in flood["text"] and flood["kind"] == "attributed"


def test_syndicated_duplicate_counts_once(result):
    r, _ = result
    p = next(p for p in r["packets"] if p["section"] == "Europe / Russia")
    assert p["independent_origins"] == 2  # bbc + reuters (Al Jazeera copy shares the reuters origin)


@pytest.mark.parametrize("case,needle", [
    ("fabricated_citation", "does not resolve"), ("misattributed_citation", "different event"), ("invented_number", "number"),
    ("invented_name", "name"), ("unhedged_weak_claim", "attributed"), ("prompt_injection_text", "injected"), ("unknown_event", "unknown event"),
    ("unknown_url", "unknown URL"), ("unsupported_assertion", "assertive"), ("overlong", "word count")])
def test_adversarial_outputs_rejected_for_the_right_reason(result, case, needle):
    from daily_wire.verify import verify
    r, _ = result
    b = r["briefing"]
    head = {k: b[k] for k in ("edition", "generated_at", "window_start", "window_end")}
    srcs = [{"n": e["n"], "url": "", "title": e["title"]} for p in r["packets"] for e in p["evidence"]]
    errs, out = verify(adversarial_cases(r["packets"])[case], r["packets"], srcs, head, CFG)
    assert out is None and any(needle in e for e in errs), errs


def test_misleading_header_dates_rejected(result):
    from daily_wire.verify import verify
    r, _ = result
    b = r["briefing"]
    head = {k: b[k] for k in ("edition", "generated_at", "window_start", "window_end")}
    srcs = [{"n": e["n"], "url": "", "title": e["title"]} for p in r["packets"] for e in p["evidence"]]
    from daily_wire.summarize import evidence_only_write
    w = evidence_only_write(r["packets"])
    assert verify(w, r["packets"], srcs, {**head, "edition": "2026-10-31"}, CFG)[0]
    assert verify(w, r["packets"], srcs, {**head, "window_start": head["window_end"]}, CFG)[0]


def test_rerun_repeats_nothing_and_publishes_short_edition(result):
    _, site = result
    r2 = run(CFG, SOURCES, FixtureFetcher(FX), NOW, site, None, "TEST")
    assert r2["briefing"]["events"] == [] and "No developments" in r2["briefing"]["bluf"]
    r3 = run(CFG, SOURCES, FixtureFetcher(FX, FX / "day2"), NOW, site, None, "TEST")
    assert [e["status"] for e in r3["briefing"]["events"]] == ["updated"]
    assert r3["briefing"]["changes"][0]["text"].startswith("Updated since previous brief")


def test_all_sources_failing_retains_previous(tmp_path):
    r = run(CFG, [SOURCES[7]], FixtureFetcher(FX), NOW, tmp_path, None)
    assert r["status"] == "stale" and not (tmp_path / "editions").exists()


# ---- EPUB / OPDS / publish
def test_epub_valid_compact_and_clickable(result):
    r, site = result
    data = (site / "editions" / "briefing-2026-10-30.epub").read_bytes()
    assert validate_epub(data) == [] and len(data) < 20_000
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.namelist()[0] == "mimetype"
    html = z.read("OEBPS/brief.xhtml").decode()
    assert 'href="#s1"' in html and 'id="s1"' in html and "https://news.example.test" in html and "TEST" in html


def test_epub_escapes_untrusted_text(result):
    r, _ = result
    b = json.loads(json.dumps(r["briefing"]))
    b["bluf"] = "<script>alert(1)</script> & <b>"
    b["sources"][0]["url"] = "javascript:alert(1)"
    data = render_epub(b)
    html = zipfile.ZipFile(io.BytesIO(data)).read("OEBPS/brief.xhtml").decode()
    assert "<script" not in html and "javascript:" not in html and validate_epub(data) == []


def test_epub_validator_catches_breakage():
    assert validate_epub(b"nope")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "wrong")
    assert validate_epub(buf.getvalue())


def test_opds_catalog_koreader_shape(result):
    _, site = result
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.parse(site / "opds.xml").getroot()
    assert root.find("a:id", ns) is not None and root.find("a:title", ns) is not None and root.find("a:updated", ns) is not None
    assert any(l.get("rel") == "self" for l in root.findall("a:link", ns))
    entry = root.find("a:entry", ns)
    acq = [l for l in entry.findall("a:link", ns) if l.get("rel") == "http://opds-spec.org/acquisition"][0]
    assert acq.get("type") == "application/epub+zip" and (site / acq.get("href")).exists()
    absolute = ET.fromstring(build_feed([{"edition": "2026-10-30", "generated_at": "2026-10-30T12:00:00+00:00", "mode": "llm", "words": 500}], "T", "https://u.github.io/dw/"))
    assert absolute.find("a:entry/a:link", ns).get("href") == "https://u.github.io/dw/editions/briefing-2026-10-30.epub"


def test_atom_feed_has_escaped_full_text_and_safe_links(result):
    _, site = result
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.parse(site / "feed.xml").getroot()
    entry = root.find("a:entry", ns)
    assert entry.find("a:id", ns).text.startswith("urn:daily-wire:") and entry.find("a:content", ns).get("type") == "html"
    b = json.loads(next((site / "editions").glob("briefing-*.json")).read_text())
    b["sources"][0].update(url="javascript:alert(1)", title="<script>x</script>")
    xml = build_atom([b], "T")
    assert "javascript:" not in xml and "<script>" not in xml
    ET.fromstring(xml)


def test_publish_confined_to_output_dir(tmp_path):
    with pytest.raises(ValueError):
        _safe(tmp_path, "../evil")
    with pytest.raises(ValueError):
        publish(tmp_path, {"edition": "../../etc"}, CFG)


def test_health_check(result):
    _, site = result
    assert health(site, NOW + timedelta(hours=1), 36) == []
    assert any("old" in p for p in health(site, NOW + timedelta(hours=72), 36))
    assert health(site / "missing", NOW, 36) == ["status.json missing"]


def test_fixture_evaluation_passes():
    res = evaluate(FX, ROOT / "config" / "briefing.yaml")
    assert res["passed"], res["checks"]


def test_no_secrets_in_artifacts(result):
    _, site = result
    for f in site.rglob("*.json"):
        assert "api_key" not in f.read_text().lower() and "sk-" not in f.read_text()


class _Bad:
    def __init__(self, text):
        self.text = text

    def complete(self, system, user, max_out):
        assert "untrusted DATA" in system and user.startswith("<evidence>")
        return self.text, 100, 50


@pytest.mark.parametrize("text", ["not json at all", json.dumps({"bluf": "x", "statements": [{"event_id": "E1", "text": "Invented claim 999", "kind": "observed", "refs": [1]}]})])
def test_bad_llm_output_falls_back_to_evidence_only(tmp_path, text):
    r = run(CFG, SOURCES, FixtureFetcher(FX), NOW, tmp_path, _Bad(text), "TEST")
    b = r["briefing"]
    assert b["mode"] == "evidence-only" and any("evidence-only" in w for w in b["warnings"]) and b["usage"]["calls"] == CFG["llm"]["max_attempts"]


def test_fallback_omits_event_with_unverifiable_headline(tmp_path, monkeypatch):
    import daily_wire.pipeline as pl
    real = pl.build_packets

    def tainted(*a, **k):
        packets, srcs = real(*a, **k)
        packets[0]["evidence"][0]["title"] += " see http://unlisted.example/x"
        return packets, srcs

    monkeypatch.setattr(pl, "build_packets", tainted)
    r = run(CFG, SOURCES, FixtureFetcher(FX), NOW, tmp_path, None, "TEST")
    cited = {s["event_id"] for sec in r["briefing"]["sections"] for s in sec["items"]}
    assert r["status"] == "published" and "E1" not in cited and "unlisted.example" not in json.dumps(r["briefing"])


def test_cli_hour_guard_and_dry_run(tmp_path, capsys):
    from daily_wire.cli import main
    base = ["run", "--fixtures", str(FX), "--site", str(tmp_path), "--config", str(ROOT / "config/briefing.yaml"), "--no-llm"]
    assert main(base + ["--now", "2026-10-30T14:00:00Z", "--require-hour"]) == 0 and not (tmp_path / "opds.xml").exists()  # 08:00 MDT
    assert main(base + ["--now", "2026-10-30T12:00:00Z", "--require-hour"]) == 0 and (tmp_path / "opds.xml").exists()  # 06:00 MDT
    capsys.readouterr()
    from zoneinfo import ZoneInfo
    # Winter 06:00 local, derived from the tz database so the test does not hard-code Alberta's offset.
    winter = datetime(2026, 12, 15, 6, tzinfo=ZoneInfo("America/Edmonton")).astimezone(timezone.utc).isoformat()
    assert main(base + ["--now", winter, "--require-hour"]) == 0
    assert '"edition": "2026-12-15"' in capsys.readouterr().out


def test_copilot_cli_provider_command_and_failure(monkeypatch):
    import subprocess
    from daily_wire.summarize import CopilotCLI
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout='{"bluf": "x", "statements": []}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake)
    text, tin, tout = CopilotCLI({"model": "m"}).complete("sys", "<evidence>\n[]\n</evidence>", 100)
    assert json.loads(text)["bluf"] == "x" and "--available-tools" in seen["cmd"] and not any(a.startswith("--allow") for a in seen["cmd"])
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="auth"))
    with pytest.raises(RuntimeError):
        CopilotCLI({}).complete("s", "u", 1)


def test_grounding_handles_hyphenated_names():
    from daily_wire.verify import check_grounding
    corpus = "coup attempt reported in guinea-bissau, officials say"
    assert check_grounding("Officials report a coup attempt in Guinea-Bissau", corpus) == []
    assert check_grounding("Officials report a coup attempt in Chad", corpus)


def test_parse_writer_output_tolerates_wrapping_and_reports_garbage():
    from daily_wire.summarize import parse_writer_output
    assert parse_writer_output('Here you go:\n```json\n{"bluf": "x"}\n```') == {"bluf": "x"}
    assert parse_writer_output('Sure. {"bluf": "x"} Done.') == {"bluf": "x"}
    with pytest.raises(ValueError, match="not JSON"):
        parse_writer_output("OK")
