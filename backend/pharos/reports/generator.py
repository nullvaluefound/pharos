"""Report generation pipeline.

Steps:
  1. Run a SearchQuery-like filter against ``all_articles`` (hot+cold) to
     gather the articles the report should cover. Capped to ``MAX_ARTICLES``
     to bound LLM cost.
  2. For each article, render a compact prompt block containing title +
     overview + extracted MITRE/CVE/IOC metadata.
  3. Submit to OpenAI Chat Completions and return the Markdown body the
     model produces.

Cost envelope (gpt-4o, USD):
  - input  $2.50 / 1M tokens
  - output $10.00 / 1M tokens
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from ..config import get_settings
from .prompts import (
    article_block,
    build_user_prompt,
    length_targets,
    system_prompt,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_ARTICLES = 200      # safety cap; dominated by token budget anyway
INPUT_PRICE = 2.50      # USD / 1M tokens (gpt-4o)
OUTPUT_PRICE = 10.00


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ReportRequest:
    """User-facing request shape. Mirrors the API payload."""
    name: str
    # Filter:
    keywords: list[str] = field(default_factory=list)  # OR keyword filter
    since_days: int | None = 14
    feed_ids: list[int] | None = None
    # Same metadata-filter shape used by /search and /watches:
    any_of: dict[str, list[str]] = field(default_factory=dict)
    all_of: dict[str, list[str]] = field(default_factory=dict)
    has_entity_types: list[str] = field(default_factory=list)
    # Output spec:
    structure_kind: str = "BLUF"            # "BLUF" | "custom"
    sections: list[str] = field(default_factory=list)
    audience: str = "both"                  # "executive" | "technical" | "both"
    length: str = "short"                   # "short" | "medium" | "long"
    scope_note: str = ""                    # free-text user comment


@dataclass(slots=True)
class ReportResult:
    body_md: str
    article_ids: list[int]
    article_count: int
    cost_usd: float
    model: str
    prompt_tokens: int
    completion_tokens: int


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens * INPUT_PRICE / 1_000_000
        + completion_tokens * OUTPUT_PRICE / 1_000_000
    )


# ---------------------------------------------------------------------------
# Article collection
# ---------------------------------------------------------------------------
def _entity_id_set(conn: sqlite3.Connection, type_: str,
                   names: list[str]) -> list[int]:
    if not names:
        return []
    placeholders = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT id FROM main.entities WHERE type = ? "
        f"AND canonical_name IN ({placeholders})",
        (type_, *[n.lower() for n in names]),
    ).fetchall()
    return [r["id"] for r in rows]


def collect_articles(conn: sqlite3.Connection, *, user_id: int,
                     req: ReportRequest, limit: int = MAX_ARTICLES) -> list[dict]:
    """Resolve ``req`` into the article rows the report should consume.

    Returns ordered-by-published-DESC list of plain dicts containing the
    fields the prompt builder needs. Mirrors search.py logic so behavior
    is consistent with what the user would see in /search."""
    where = ["s.user_id = ?"]
    params: list[Any] = [user_id]

    if req.feed_ids:
        ph = ",".join("?" * len(req.feed_ids))
        where.append(f"a.feed_id IN ({ph})")
        params.extend(req.feed_ids)

    if req.since_days:
        where.append("a.published_at > datetime('now', ?)")
        params.append(f"-{int(req.since_days)} days")

    # Keyword OR filter via FTS5. Group keywords with OR.
    if req.keywords:
        # Sanitize: strip out FTS metacharacters that would break the parse.
        cleaned = [
            "".join(ch for ch in k if ch.isalnum() or ch in " -_")
            for k in req.keywords if k and k.strip()
        ]
        cleaned = [c.strip() for c in cleaned if c.strip()]
        if cleaned:
            # FTS5 OR: "alpha" OR "beta gamma"
            fts_query = " OR ".join(f'"{c}"' for c in cleaned)
            where.append(
                "a.id IN (SELECT rowid FROM main.articles_fts "
                "WHERE articles_fts MATCH ?)"
            )
            params.append(fts_query)

    # any_of: union of entity matches
    any_ids: list[int] = []
    for t, names in (req.any_of or {}).items():
        any_ids.extend(_entity_id_set(conn, t, names))
    if req.any_of and not any_ids:
        # User asked for entities that don't exist -> empty corpus.
        return []
    if any_ids:
        ph = ",".join("?" * len(any_ids))
        where.append(
            f"a.id IN (SELECT article_id FROM main.article_entities "
            f"WHERE entity_id IN ({ph}))"
        )
        params.extend(any_ids)

    # all_of: each entity must be present
    for t, names in (req.all_of or {}).items():
        for eid in _entity_id_set(conn, t, names):
            where.append(
                "a.id IN (SELECT article_id FROM main.article_entities "
                "WHERE entity_id = ?)"
            )
            params.append(eid)

    # has_entity_types: e.g. require ANY threat_actor entity
    for etype in req.has_entity_types or []:
        where.append(
            "a.id IN (SELECT ae.article_id FROM main.article_entities ae "
            "JOIN main.entities e ON e.id = ae.entity_id WHERE e.type = ?)"
        )
        params.append(etype)

    # Only enriched articles -- a report on un-enriched data has no metadata
    # to ground the model.
    where.append("a.enrichment_status = 'enriched'")

    sql = f"""
        SELECT a.id, a.feed_id, f.title AS feed_title, a.url, a.title,
               a.published_at, a.overview, a.severity_hint,
               a.enriched_json
          FROM all_articles a
          JOIN main.subscriptions s ON s.feed_id = a.feed_id
          LEFT JOIN main.feeds f ON f.id = a.feed_id
         WHERE {' AND '.join(where)}
         ORDER BY a.published_at DESC NULLS LAST
         LIMIT ?
    """
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        ej = d.pop("enriched_json", None)
        try:
            d["enriched"] = json.loads(ej) if ej else None
        except Exception:
            d["enriched"] = None
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# OpenAI invocation
# ---------------------------------------------------------------------------
def _client() -> AsyncOpenAI:
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if os.environ.get("OPENAI_BASE_URL", "").strip() == "":
        os.environ.pop("OPENAI_BASE_URL", None)
    return AsyncOpenAI(
        api_key=s.openai_api_key,
        base_url=(s.openai_base_url or "").strip() or None,
    )


def _is_reasoning_model(model: str) -> bool:
    m = model.lower()
    return m.startswith(("o1", "o3", "o4")) or "reasoning" in m


async def generate_report(*, user_id: int, conn: sqlite3.Connection,
                          req: ReportRequest) -> ReportResult:
    s = get_settings()
    client = _client()
    model = s.openai_model

    rows = collect_articles(conn, user_id=user_id, req=req)
    if not rows:
        raise RuntimeError(
            "No enriched articles match this filter. Try widening the "
            "timeframe, removing keyword filters, or relaxing the metadata "
            "requirements."
        )

    blocks = [
        article_block(
            i + 1,
            title=r["title"],
            url=r["url"],
            published_at=r["published_at"],
            feed_title=r.get("feed_title"),
            overview=r.get("overview"),
            severity=r.get("severity_hint"),
            enriched=r.get("enriched"),
        )
        for i, r in enumerate(rows)
    ]

    sys_msg = system_prompt(
        structure_kind=req.structure_kind,
        sections=req.sections,
        audience=req.audience,
        length=req.length,
    )
    user_msg = build_user_prompt(
        name=req.name,
        scope_text=req.scope_note,
        article_blocks=blocks,
    )
    _, _, max_output = length_targets(req.length)

    log.info(
        "generating report '%s' for user=%s model=%s articles=%s "
        "structure=%s audience=%s length=%s",
        req.name, user_id, model, len(rows),
        req.structure_kind, req.audience, req.length,
    )

    kwargs: dict[str, Any] = dict(
        model=model,
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=max_output,
    )
    if not _is_reasoning_model(model):
        kwargs["temperature"] = 0.3  # a touch of creativity is fine for prose

    resp = await client.chat.completions.create(**kwargs)
    if not resp.choices:
        raise RuntimeError("OpenAI returned no choices")
    msg = resp.choices[0].message
    body = (msg.content or "").strip()
    if not body:
        raise RuntimeError("OpenAI returned an empty report body")

    usage = resp.usage
    pt = int(usage.prompt_tokens or 0) if usage else 0
    ct = int(usage.completion_tokens or 0) if usage else 0
    cost = estimate_cost(pt, ct)

    return ReportResult(
        body_md=body,
        article_ids=[int(r["id"]) for r in rows],
        article_count=len(rows),
        cost_usd=cost,
        model=model,
        prompt_tokens=pt,
        completion_tokens=ct,
    )
