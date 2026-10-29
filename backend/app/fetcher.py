"""Downloads camera images and tells new frames apart from repeats."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import cv2
import httpx
import numpy as np

DEFAULT_UA = "Mozilla/5.0 (X11; Linux x86_64) TrafficWebcamMonitor/1.0"


@dataclass
class FetchResult:
    status: str  # "new" | "unchanged" | "error"
    data: bytes = b""
    image: np.ndarray | None = None
    sha: str = ""
    etag: str | None = None
    last_modified: str | None = None
    error: str = ""


def _bust(url: str) -> str:
    parts = urlparse(url)
    q = parse_qsl(parts.query, keep_blank_values=True)
    q.append(("_tw", str(int(time.time()))))
    return urlunparse(parts._replace(query=urlencode(q)))


def looks_incomplete(data: bytes) -> bool:
    """Camera servers often serve a file while it's being rewritten: all zeros, or a JPEG missing its end marker."""
    if not data or not data[:64].strip(b"\x00"):
        return True
    if data[:2] == b"\xff\xd8":
        return b"\xff\xd9" not in data[-64:]
    return False


def decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, dtype=np.uint8)
    if arr.size == 0:
        return None
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    headers: dict | None = None,
    cache_bust: bool = False,
    etag: str | None = None,
    last_modified: str | None = None,
    last_hash: str | None = None,
    retries: int = 2,
) -> FetchResult:
    """Fetch, retrying a few seconds later when the server hands out a half-written image."""
    for attempt in range(retries + 1):
        res = await _fetch_once(client, url, headers, cache_bust, etag, last_modified, last_hash)
        if not res.error.startswith("Incomplete image") or attempt == retries:
            return res
        await asyncio.sleep(4)
    return res


async def _fetch_once(
    client: httpx.AsyncClient,
    url: str,
    headers: dict | None = None,
    cache_bust: bool = False,
    etag: str | None = None,
    last_modified: str | None = None,
    last_hash: str | None = None,
) -> FetchResult:
    h = {"User-Agent": DEFAULT_UA, "Accept": "image/*,*/*;q=0.8"}
    h.update(headers or {})
    if etag:
        h["If-None-Match"] = etag
    if last_modified:
        h["If-Modified-Since"] = last_modified
    try:
        resp = await client.get(_bust(url) if cache_bust else url, headers=h, follow_redirects=True, timeout=20)
    except httpx.HTTPError as e:
        return FetchResult("error", error=f"{type(e).__name__}: {e}"[:300])
    if resp.status_code == 304:
        return FetchResult("unchanged", etag=etag, last_modified=last_modified, sha=last_hash or "")
    if resp.status_code >= 400:
        return FetchResult("error", error=f"HTTP {resp.status_code}")
    data = resp.content
    if looks_incomplete(data):
        return FetchResult("error", error=f"Incomplete image ({len(data)} bytes); server was mid-update")
    image = decode_image(data)
    if image is None:
        ctype = resp.headers.get("content-type", "?")
        return FetchResult("error", error=f"Response is not an image (content-type {ctype}, {len(data)} bytes)")
    sha = hashlib.sha256(data).hexdigest()
    result = FetchResult(
        "unchanged" if sha == last_hash else "new",
        data=data, image=image, sha=sha,
        etag=resp.headers.get("etag"), last_modified=resp.headers.get("last-modified"),
    )
    return result
