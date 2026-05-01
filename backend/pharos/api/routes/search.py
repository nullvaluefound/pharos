"""Structured search across articles using the inverted entity index + FTS5.

Supports a ``tier`` filter so the UI can scope a search to fresh data
(``hot``, recent ~3 months) or to the deeper archive (``cold``). Defaults
to ``all`` (UNION ALL across both DBs through the ``all_articles`` view).

A separate ``ArchiveSearchPage`` on the frontend hits this endpoint with
``tier=cold`` -- that path runs against the cold DB only, which is bigger
and slower but still fully searchable.
"""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/search", tags=["search"])


class SearchQuery(BaseModel):
    """Structured filter. Each *_of map keys are entity types, values are
    canonical entity names (lowercase). Example::

        {
            "any_of": {"threat_actor": ["apt29"], "cve": ["cve-2024-12345"]},
            "all_of": {"sector": ["finance"]},
            "none_of": {"vendor": ["vendor-i-dont-care"]},
            "text": "supply chain",
            "since_days": 14,
            "feed_ids": [1, 2]
        }
    """
    any_of: dict[str, list[str]] = Field(default_factory=dict)
    all_of: dict[str, list[str]] = Field(default_factory=dict)
    none_of: dict[str, list[str]] = Field(default_factory=dict)
    has_entity_types: list[str] | None = Field(
        default=None,
        description="Only return articles that have at least one entity of each listed type "
                    "(e.g. ['cve', 'ttp_mitre'] = must have CVEs AND TTPs)",
    )
    text: str | None = None
    since_days: int | None = Field(default=None, ge=1, le=3650)
    feed_ids: list[int] | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = Field(
        default=None,
        description="published_at of the last item from the previous page; "
                    "results returned will be strictly older than this.",
    )
    tier: Literal["hot", "cold", "all"] = Field(
        default="all",
        description="hot=recent (~3 months); cold=archive; all=both. "
                    "Cold is slower but lets you search the full history.",
    )


class SearchHit(BaseModel):
    id: int
    feed_id: int
    feed_title: str | None
    url: str
    title: str | None
    published_at: str | None
    overview: str | None
    severity_hint: str | None
    story_cluster_id: int | None
    tier: str


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    count: int
    next_cursor: str | None = None


def _entity_id_set(conn: sqlite3.Connection, type_: str, names: list[str]) -> list[int]:
    if not names:
        return []
    placeholders = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT id FROM main.entities WHERE type = ? AND canonical_name IN ({placeholders})",
        (type_, *[n.lower() for n in names]),
    ).fetchall()
    return [r["id"] for r in rows]


def _entity_subquery(tier: str, ids: list[int]) -> str:
    """`a.id IN (...)` that respects the tier scope. The hot and cold DBs
    each have their own ``article_entities`` table sharing the same
    ``entities`` dimension (which lives in hot)."""
    ph = ",".join("?" * len(ids))
    if tier == "hot":
        return (f"a.id IN (SELECT article_id FROM main.article_entities "
                f"WHERE entity_id IN ({ph}))")
    if tier == "cold":
        return (f"a.id IN (SELECT article_id FROM cold.article_entities "
                f"WHERE entity_id IN ({ph}))")
    return (
        f"a.id IN ("
        f"  SELECT article_id FROM main.article_entities WHERE entity_id IN ({ph}) "
        f"  UNION ALL "
        f"  SELECT article_id FROM cold.article_entities WHERE entity_id IN ({ph})"
        f")"
    )


def _has_type_subquery(tier: str) -> str:
    if tier == "hot":
        return (
            "a.id IN (SELECT ae.article_id FROM main.article_entities ae "
            "JOIN main.entities e ON e.id = ae.entity_id WHERE e.type = ?)"
        )
    if tier == "cold":
        return (
            "a.id IN (SELECT ae.article_id FROM cold.article_entities ae "
            "JOIN main.entities e ON e.id = ae.entity_id WHERE e.type = ?)"
        )
    return (
        "a.id IN ("
        "  SELECT ae.article_id FROM main.article_entities ae "
        "    JOIN main.entities e ON e.id = ae.entity_id WHERE e.type = ? "
        "  UNION ALL "
        "  SELECT ae.article_id FROM cold.article_entities ae "
        "    JOIN main.entities e ON e.id = ae.entity_id WHERE e.type = ?"
        ")"
    )


def _fts_subquery(tier: str) -> str:
    if tier == "hot":
        return ("a.id IN (SELECT rowid FROM main.articles_fts "
                "WHERE articles_fts MATCH ?)")
    if tier == "cold":
        return ("a.id IN (SELECT rowid FROM cold.articles_fts "
                "WHERE articles_fts MATCH ?)")
    return (
        "a.id IN ("
        "  SELECT rowid FROM main.articles_fts WHERE articles_fts MATCH ? "
        "  UNION ALL "
        "  SELECT rowid FROM cold.articles_fts WHERE articles_fts MATCH ?"
        ")"
    )


@router.post("", response_model=SearchResponse)
def search(query: SearchQuery,
           user: CurrentUser = Depends(get_current_user),
           conn: sqlite3.Connection = Depends(get_db)) -> SearchResponse:
    tier = query.tier
    where = ["s.user_id = ?"]
    params: list = [user.id]

    if tier in ("hot", "cold"):
        where.append("a.tier = ?")
        params.append(tier)

    if query.feed_ids:
        ph = ",".join("?" * len(query.feed_ids))
        where.append(f"a.feed_id IN ({ph})")
        params.extend(query.feed_ids)

    if query.since_days:
        where.append("a.published_at > datetime('now', ?)")
        params.append(f"-{query.since_days} days")

    if query.cursor:
        where.append("a.published_at < ?")
        params.append(query.cursor)

    # any_of: union of entity matches must intersect the article
    any_ids: list[int] = []
    for t, names in query.any_of.items():
        any_ids.extend(_entity_id_set(conn, t, names))
    if query.any_of and not any_ids:
        return SearchResponse(hits=[], count=0)
    if any_ids:
        clause = _entity_subquery(tier, any_ids)
        where.append(clause)
        # _entity_subquery embeds the placeholders once for hot/cold and
        # twice for "all".
        if tier == "all":
            params.extend(any_ids)
            params.extend(any_ids)
        else:
            params.extend(any_ids)

    for t, names in query.all_of.items():
        for eid in _entity_id_set(conn, t, names):
            where.append(_entity_subquery(tier, [eid]))
            if tier == "all":
                params.extend([eid, eid])
            else:
                params.append(eid)

    for t, names in query.none_of.items():
        ids = _entity_id_set(conn, t, names)
        if not ids:
            continue
        sub = _entity_subquery(tier, ids).replace("a.id IN", "a.id NOT IN", 1)
        where.append(sub)
        if tier == "all":
            params.extend(ids)
            params.extend(ids)
        else:
            params.extend(ids)

    if query.has_entity_types:
        for etype in query.has_entity_types:
            where.append(_has_type_subquery(tier))
            if tier == "all":
                params.extend([etype, etype])
            else:
                params.append(etype)

    if query.text:
        where.append(_fts_subquery(tier))
        if tier == "all":
            params.extend([query.text, query.text])
        else:
            params.append(query.text)

    sql = f"""
        SELECT a.id, a.feed_id, f.title AS feed_title, a.url, a.title,
               a.published_at, a.overview, a.severity_hint,
               a.story_cluster_id, a.tier
          FROM all_articles a
          JOIN main.subscriptions s ON s.feed_id = a.feed_id
          LEFT JOIN main.feeds f ON f.id = a.feed_id
         WHERE {' AND '.join(where)}
         ORDER BY a.published_at DESC NULLS LAST
         LIMIT ?
    """
    params.append(query.limit + 1)
    rows = conn.execute(sql, params).fetchall()

    next_cursor: str | None = None
    if len(rows) > query.limit:
        next_cursor = rows[query.limit - 1]["published_at"]
        rows = rows[:query.limit]

    hits = [SearchHit(**dict(r)) for r in rows]
    return SearchResponse(hits=hits, count=len(hits), next_cursor=next_cursor)
