"""Stream endpoint: paginated list of articles for the current user.

Supports three filter modes (mutually exclusive in practice):
  - feed_id   : single subscribed feed
  - folder    : a user folder
  - watch_id  : a saved-search ("watch") -- the watch's metadata filter is
                applied on top of the user's subscriptions

Two view modes:
  - flat     : one row per article
  - grouped  : one row per constellation (story cluster), with shared
               keywords + weighted-Jaccard similarity surfaced for the UI

Cursor pagination uses the published_at timestamp of the last item -- the
``next_cursor`` returned in one response can be passed back as ``cursor``
to fetch the next page. The frontend uses TanStack ``useInfiniteQuery``
to drive infinite scroll.

Reads from the unified ``all_articles`` view so hot+cold are seamless
(but pagination still walks DESC by published_at, so cold articles only
surface after the user has scrolled past the entire hot window).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ...lantern.constellations import (
    NAMESPACE_WEIGHTS,
    shared_tokens,
    weighted_jaccard,
)
from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/stream", tags=["stream"])
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ArticleSummary(BaseModel):
    id: int
    feed_id: int
    feed_title: str | None
    url: str
    title: str | None
    author: str | None
    published_at: str | None
    overview: str | None
    severity_hint: str | None
    is_read: bool
    is_saved: bool
    story_cluster_id: int | None
    tier: str


class ConstellationItem(BaseModel):
    cluster_id: int
    member_count: int
    representative: ArticleSummary
    other_sources: list[ArticleSummary]
    # NEW: surface why these articles were grouped.
    shared_keywords: list[str] = []      # human-readable, top-N
    avg_similarity: float | None = None   # 0.0-1.0, mean across siblings


class StreamPage(BaseModel):
    view: Literal["flat", "grouped"]
    items: list[ArticleSummary] | list[ConstellationItem]
    next_cursor: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_article(r: sqlite3.Row) -> ArticleSummary:
    return ArticleSummary(
        id=r["id"],
        feed_id=r["feed_id"],
        feed_title=r["feed_title"],
        url=r["url"],
        title=r["title"],
        author=r["author"],
        published_at=r["published_at"],
        overview=r["overview"],
        severity_hint=r["severity_hint"],
        is_read=bool(r["is_read"]) if r["is_read"] is not None else False,
        is_saved=bool(r["is_saved"]) if r["is_saved"] is not None else False,
        story_cluster_id=r["story_cluster_id"],
        tier=r["tier"],
    )


# Pretty namespace labels for "shared keywords" chips.
_NS_LABELS: dict[str, str] = {
    "cve": "CVE",
    "mtg": "Group",
    "mts": "Software",
    "ttp": "TTP",
    "mta": "Tactic",
    "thr": "Actor",
    "mal": "Malware",
    "tool": "Tool",
    "pro": "Product",
    "com": "Company",
    "ven": "Vendor",
    "sec": "Sector",
    "geo": "Geo",
    "top": "Topic",
    "w": "kw",
}


def _format_shared_token(token: str) -> str:
    if ":" not in token:
        return token
    ns, val = token.split(":", 1)
    label = _NS_LABELS.get(ns, ns)
    # Casing: MITRE / CVE IDs are upper, free-text is title-case.
    if ns in ("cve", "mtg", "mts", "ttp", "mta"):
        return f"{label} {val.upper()}"
    return f"{label}: {val}"


def _resolve_watch_filter(
    conn: sqlite3.Connection, *, user_id: int, watch_id: int,
) -> tuple[list[str], list]:
    """Translate a saved watch's structured query into extra WHERE clauses
    + bind parameters that we can append to the stream query."""
    row = conn.execute(
        "SELECT query_json FROM main.saved_searches WHERE id = ? AND user_id = ?",
        (watch_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Watch not found")
    try:
        q = json.loads(row["query_json"]) or {}
    except Exception:
        return [], []

    where: list[str] = []
    params: list = []

    def entity_id_set(type_: str, names: list[str]) -> list[int]:
        if not names:
            return []
        ph = ",".join("?" * len(names))
        rows = conn.execute(
            f"SELECT id FROM main.entities WHERE type = ? AND canonical_name IN ({ph})",
            (type_, *[n.lower() for n in names]),
        ).fetchall()
        return [r["id"] for r in rows]

    any_ids: list[int] = []
    for t, names in (q.get("any_of") or {}).items():
        any_ids.extend(entity_id_set(t, names or []))
    if q.get("any_of") and not any_ids:
        # User asked for entities that don't exist -> force empty result.
        where.append("1 = 0")
    elif any_ids:
        ph = ",".join("?" * len(any_ids))
        where.append(
            f"a.id IN (SELECT article_id FROM main.article_entities "
            f"WHERE entity_id IN ({ph}))"
        )
        params.extend(any_ids)

    for t, names in (q.get("all_of") or {}).items():
        for eid in entity_id_set(t, names or []):
            where.append(
                "a.id IN (SELECT article_id FROM main.article_entities "
                "WHERE entity_id = ?)"
            )
            params.append(eid)

    for t, names in (q.get("none_of") or {}).items():
        ids = entity_id_set(t, names or [])
        if ids:
            ph = ",".join("?" * len(ids))
            where.append(
                f"a.id NOT IN (SELECT article_id FROM main.article_entities "
                f"WHERE entity_id IN ({ph}))"
            )
            params.extend(ids)

    for etype in q.get("has_entity_types") or []:
        where.append(
            "a.id IN (SELECT ae.article_id FROM main.article_entities ae "
            "JOIN main.entities e ON e.id = ae.entity_id WHERE e.type = ?)"
        )
        params.append(etype)

    if q.get("text"):
        where.append(
            "a.id IN (SELECT rowid FROM main.articles_fts "
            "WHERE articles_fts MATCH ?)"
        )
        params.append(q["text"])

    if q.get("since_days"):
        where.append("a.published_at > datetime('now', ?)")
        params.append(f"-{int(q['since_days'])} days")

    if q.get("feed_ids"):
        feed_ids = [int(x) for x in q["feed_ids"]]
        ph = ",".join("?" * len(feed_ids))
        where.append(f"a.feed_id IN ({ph})")
        params.extend(feed_ids)

    return where, params


def _cluster_token_set(conn: sqlite3.Connection, cluster_id: int,
                       limit_articles: int = 6) -> list[set[str]]:
    """Pull token sets for up to N articles in a cluster. We use these to
    compute the shared-keyword overlap and a per-cluster mean similarity.

    Note: ``article_tokens`` lives only in hot.db -- cold articles have
    their tokens copied to ``cold.article_tokens`` at archive time. We
    UNION ALL both so cluster-meta works across the tier boundary."""
    rows = conn.execute(
        """
        SELECT article_id, token FROM (
            SELECT at.article_id, at.token
              FROM main.article_tokens at
              JOIN main.articles a ON a.id = at.article_id
             WHERE a.story_cluster_id = ?
            UNION ALL
            SELECT at.article_id, at.token
              FROM cold.article_tokens at
              JOIN cold.articles a ON a.id = at.article_id
             WHERE a.story_cluster_id = ?
        )
        ORDER BY article_id
        LIMIT ?
        """,
        (cluster_id, cluster_id, limit_articles * 200),
    ).fetchall()
    by_article: dict[int, set[str]] = {}
    for r in rows:
        by_article.setdefault(r["article_id"], set()).add(r["token"])
    # Cap to ``limit_articles`` so big clusters don't blow up the response.
    return list(by_article.values())[:limit_articles]


def _enrich_cluster(item: ConstellationItem,
                    conn: sqlite3.Connection) -> ConstellationItem:
    """Compute ``shared_keywords`` + ``avg_similarity`` for the cluster."""
    if item.cluster_id < 0:  # synthetic single-article cluster
        return item
    sets = _cluster_token_set(conn, item.cluster_id)
    if len(sets) < 2:
        return item

    # Intersection across ALL pulled members = the strongest "this is the
    # same story" signal. Fallback: union of pairwise intersections.
    inter = set.intersection(*sets)
    if not inter:
        # Looser overlap: tokens shared by at least 2 members.
        from collections import Counter
        cnt: Counter[str] = Counter()
        for s in sets:
            for t in s:
                cnt[t] += 1
            inter = {t for t, c in cnt.items() if c >= 2}

    sorted_keys = shared_tokens(sets[0], inter) if inter else []
    item.shared_keywords = [_format_shared_token(t) for t in sorted_keys[:8]]

    # Mean pairwise similarity across the sample.
    sims: list[float] = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            sims.append(weighted_jaccard(sets[i], sets[j]))
    if sims:
        item.avg_similarity = round(sum(sims) / len(sims), 3)
    return item


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.get("", response_model=StreamPage)
def get_stream(
    view: Literal["flat", "grouped"] = "grouped",
    folder: str | None = None,
    feed_id: int | None = None,
    watch_id: int | None = None,
    only_unread: bool = False,
    only_saved: bool = False,
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> StreamPage:
    where = ["s.user_id = ?"]
    params: list = [user.id]

    if feed_id is not None:
        where.append("a.feed_id = ?")
        params.append(feed_id)
    if folder is not None:
        where.append("s.folder = ?")
        params.append(folder)
    if watch_id is not None:
        extra_where, extra_params = _resolve_watch_filter(
            conn, user_id=user.id, watch_id=watch_id,
        )
        where.extend(extra_where)
        params.extend(extra_params)
    if cursor:
        where.append("a.published_at < ?")
        params.append(cursor)
    if only_unread:
        where.append("COALESCE(uas.is_read, 0) = 0")
    if only_saved:
        where.append("COALESCE(uas.is_saved, 0) = 1")

    base_sql = f"""
        SELECT a.id, a.feed_id, f.title AS feed_title, a.url, a.title, a.author,
               a.published_at, a.overview, a.severity_hint,
               a.story_cluster_id, a.tier,
               COALESCE(uas.is_read, 0)  AS is_read,
               COALESCE(uas.is_saved, 0) AS is_saved
          FROM all_articles a
          JOIN main.subscriptions s ON s.feed_id = a.feed_id
          LEFT JOIN main.feeds f ON f.id = a.feed_id
          LEFT JOIN main.user_article_state uas
                 ON uas.article_id = a.id AND uas.user_id = s.user_id
         WHERE {' AND '.join(where)}
         ORDER BY a.published_at DESC NULLS LAST
         LIMIT ?
    """
    rows = conn.execute(base_sql, (*params, limit + 1)).fetchall()

    next_cursor: str | None = None
    if len(rows) > limit:
        next_cursor = rows[limit - 1]["published_at"]
        rows = rows[:limit]

    if view == "flat":
        return StreamPage(view="flat",
                          items=[_row_to_article(r) for r in rows],
                          next_cursor=next_cursor)

    # grouped view: collapse by story_cluster_id, fetch siblings for each.
    seen_clusters: set[int] = set()
    grouped: list[ConstellationItem] = []
    for r in rows:
        cluster_id = r["story_cluster_id"]
        if cluster_id is None:
            grouped.append(
                ConstellationItem(
                    cluster_id=-r["id"],
                    member_count=1,
                    representative=_row_to_article(r),
                    other_sources=[],
                )
            )
            continue
        if cluster_id in seen_clusters:
            continue
        seen_clusters.add(cluster_id)

        siblings = conn.execute(
            """
            SELECT a.id, a.feed_id, f.title AS feed_title, a.url, a.title, a.author,
                   a.published_at, a.overview, a.severity_hint,
                   a.story_cluster_id, a.tier,
                   COALESCE(uas.is_read, 0) AS is_read,
                   COALESCE(uas.is_saved, 0) AS is_saved
              FROM all_articles a
              LEFT JOIN main.feeds f ON f.id = a.feed_id
              LEFT JOIN main.user_article_state uas
                     ON uas.article_id = a.id AND uas.user_id = ?
             WHERE a.story_cluster_id = ? AND a.id != ?
             ORDER BY a.published_at DESC NULLS LAST
             LIMIT 5
            """,
            (user.id, cluster_id, r["id"]),
        ).fetchall()

        member_count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM all_articles WHERE story_cluster_id = ?",
            (cluster_id,),
        ).fetchone()
        member_count = int(member_count_row["c"]) if member_count_row else 1

        item = ConstellationItem(
            cluster_id=cluster_id,
            member_count=member_count,
            representative=_row_to_article(r),
            other_sources=[_row_to_article(s) for s in siblings],
        )
        try:
            item = _enrich_cluster(item, conn)
        except Exception as exc:
            log.debug("cluster meta enrich failed for %s: %s", cluster_id, exc)
        grouped.append(item)

    # Suppress namespace prefix in unused weights import.
    _ = NAMESPACE_WEIGHTS
    return StreamPage(view="grouped", items=grouped, next_cursor=next_cursor)
