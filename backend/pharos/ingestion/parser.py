"""Feed parsing: dispatch RSS/Atom/JSON Feed via feedparser into a canonical schema."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import struct_time
from typing import Iterable

import feedparser


@dataclass
class ParsedEntry:
    url: str
    title: str | None
    author: str | None
    published_at: datetime | None
    summary_html: str | None
    content_html: str | None


@dataclass
class ParsedFeed:
    title: str | None
    site_url: str | None
    entries: list[ParsedEntry]


def _to_datetime(t: struct_time | None) -> datetime | None:
    if not t:
        return None
    try:
        return datetime(*t[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _first_link(entry) -> str | None:  # type: ignore[no-untyped-def]
    if getattr(entry, "link", None):
        return entry.link
    for link in getattr(entry, "links", []) or []:
        href = link.get("href") if isinstance(link, dict) else None
        if href:
            return href
    return None


def _content_html(entry) -> str | None:  # type: ignore[no-untyped-def]
    contents: Iterable = getattr(entry, "content", None) or []
    for c in contents:
        value = c.get("value") if isinstance(c, dict) else None
        if value:
            return value
    return None


def parse_feed(body: bytes | str) -> ParsedFeed:
    parsed = feedparser.parse(body)
    feed_meta = parsed.feed if hasattr(parsed, "feed") else {}

    entries: list[ParsedEntry] = []
    for entry in parsed.entries or []:
        link = _first_link(entry)
        if not link:
            continue
        published = _to_datetime(getattr(entry, "published_parsed", None)) or _to_datetime(
            getattr(entry, "updated_parsed", None)
        )
        author = getattr(entry, "author", None)
        if not author and getattr(entry, "authors", None):
            try:
                author = entry.authors[0].get("name")
            except (AttributeError, IndexError, TypeError):
                author = None
        entries.append(
            ParsedEntry(
                url=link,
                title=getattr(entry, "title", None),
                author=author,
                published_at=published,
                summary_html=getattr(entry, "summary", None),
                content_html=_content_html(entry),
            )
        )

    return ParsedFeed(
        title=getattr(feed_meta, "title", None),
        site_url=getattr(feed_meta, "link", None),
        entries=entries,
    )
