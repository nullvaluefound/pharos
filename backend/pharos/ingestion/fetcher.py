"""HTTP fetcher with conditional GET (ETag / If-Modified-Since)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    status_code: int
    body: bytes
    etag: str | None
    last_modified: str | None
    final_url: str
    not_modified: bool


async def fetch(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: float = 20.0,
) -> FetchResult:
    """Fetch a URL with conditional GET headers."""
    s = get_settings()
    headers = {
        "User-Agent": s.http_user_agent,
        "Accept": (
            "application/atom+xml,application/rss+xml,application/xml;q=0.9,"
            "application/json;q=0.9,text/html;q=0.8,*/*;q=0.5"
        ),
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, headers=headers
    ) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            log.warning("fetch failed for %s: %s", url, exc)
            raise

    if resp.status_code == 304:
        return FetchResult(
            status_code=304,
            body=b"",
            etag=etag,
            last_modified=last_modified,
            final_url=str(resp.url),
            not_modified=True,
        )
    return FetchResult(
        status_code=resp.status_code,
        body=resp.content,
        etag=resp.headers.get("etag"),
        last_modified=resp.headers.get("last-modified"),
        final_url=str(resp.url),
        not_modified=False,
    )


async def fetch_article_html(url: str, *, timeout: float = 20.0) -> str | None:
    """Fetch the full HTML of an article URL (best-effort)."""
    s = get_settings()
    headers = {
        "User-Agent": s.http_user_agent,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    }
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, headers=headers
    ) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            log.warning("article fetch failed for %s: %s", url, exc)
            return None
    if resp.status_code >= 400:
        return None
    return resp.text
