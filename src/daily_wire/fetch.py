"""Safe HTTP fetching: HTTPS only, SSRF/redirect guarding, size/time limits, retries, conditional GET."""
from __future__ import annotations

import ipaddress
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

USER_AGENT = "Mozilla/5.0 (compatible; daily-wire/0.1; +https://github.com/dcasati/daily-wire)"
MAX_BYTES = 3_000_000


class FetchError(Exception):
    pass


def check_url(url: str) -> None:
    """Reject non-HTTPS, credentialed, non-443, or non-public destinations."""
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise FetchError(f"unsafe url scheme/userinfo: {url[:80]}")
    if u.port not in (None, 443):
        raise FetchError("unsafe port")
    try:
        infos = socket.getaddrinfo(u.hostname, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchError(f"dns failure: {u.hostname}") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise FetchError(f"non-public address for {u.hostname}")
    # Residual risk: DNS rebinding between this check and connect (see docs/architecture.md).


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, cache: dict | None = None, timeout: float = 15, retries: int = 2) -> tuple[bytes | None, dict]:
    """Return (body or None if 304, new cache validators)."""
    check_url(url)
    cache = cache or {}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}
    if cache.get("etag"):
        headers["If-None-Match"] = cache["etag"]
    if cache.get("last_modified"):
        headers["If-Modified-Since"] = cache["last_modified"]
    opener = urllib.request.build_opener(_SafeRedirect)
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
                body = resp.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise FetchError("response too large")
                return body, {"etag": resp.headers.get("ETag"), "last_modified": resp.headers.get("Last-Modified")}
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return None, cache
            last = exc
            if exc.code < 500 and exc.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        time.sleep(min(2**attempt, 4))
    raise FetchError(f"fetch failed: {last}")


class FixtureFetcher:
    """Offline fetcher: reads <dir>/<source id>.xml (optionally overlaid by <overlay>/<id>.xml)."""

    def __init__(self, directory: str | Path, overlay: str | Path | None = None):
        self.dir, self.overlay = Path(directory), Path(overlay) if overlay else None

    def __call__(self, source: dict, cache: dict) -> tuple[bytes | None, dict]:
        for d in (self.overlay, self.dir):
            if d and (d / f"{source['id']}.xml").exists():
                return (d / f"{source['id']}.xml").read_bytes(), {}
        raise FetchError(f"no fixture for {source['id']}")


def live_fetcher(source: dict, cache: dict) -> tuple[bytes | None, dict]:
    return fetch(source["url"], cache)


def fetch_all(sources: list[dict], fetcher, caches: dict, workers: int = 4) -> dict[str, tuple[bytes | None, dict] | Exception]:
    """Bounded-concurrency fetch; failures are returned, not raised."""

    def one(src: dict):
        try:
            return src["id"], fetcher(src, caches.get(src["id"], {}))
        except Exception as exc:  # noqa: BLE001 - source failure must not abort the run
            return src["id"], exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, sources))
