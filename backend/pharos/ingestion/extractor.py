"""Readability-style extraction of clean article text from HTML."""
from __future__ import annotations

import logging
import re

import trafilatura

log = logging.getLogger(__name__)

_html_tag_re = re.compile(r"<[^>]+>")
_whitespace_re = re.compile(r"\s+")


def strip_html(html: str) -> str:
    """Crude HTML-to-text fallback when trafilatura returns nothing."""
    text = _html_tag_re.sub(" ", html)
    return _whitespace_re.sub(" ", text).strip()


def extract_text(html: str | None, *, url: str | None = None) -> str:
    """Return the cleanest plain-text version of an article body we can get."""
    if not html:
        return ""
    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
    except Exception as exc:
        log.warning("trafilatura failed for %s: %s", url, exc)
        text = None
    if text and text.strip():
        return text.strip()
    return strip_html(html)
