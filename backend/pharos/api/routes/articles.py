"""Article detail + related (constellation siblings) endpoints."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...lantern import mitre
from ...lantern.constellations import shared_tokens, weighted_jaccard
from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/articles", tags=["articles"])


class ArticleDetail(BaseModel):
    id: int
    feed_id: int
    feed_title: str | None
    url: str
    title: str | None
    author: str | None
    published_at: str | None
    overview: str | None
    enriched: dict[str, Any] | None
    severity_hint: str | None
    story_cluster_id: int | None
    is_read: bool
    is_saved: bool
    tier: str


class RelatedArticle(BaseModel):
    id: int
    feed_title: str | None
    url: str
    title: str | None
    published_at: str | None
    overview: str | None
    similarity: float
    shared_tokens: list[str]


class RelatedResponse(BaseModel):
    article_id: int
    cluster_id: int | None
    members: list[RelatedArticle]


def _fetch_tokens(conn: sqlite3.Connection, article_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT token FROM main.article_tokens WHERE article_id = ? "
        "UNION ALL SELECT token FROM cold.article_tokens WHERE article_id = ?",
        (article_id, article_id),
    ).fetchall()
    return {r["token"] for r in rows}


@router.get("/{article_id}", response_model=ArticleDetail)
def get_article(article_id: int,
                user: CurrentUser = Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)) -> ArticleDetail:
    row = conn.execute(
        """
        SELECT a.id, a.feed_id, f.title AS feed_title, a.url, a.title, a.author,
               a.published_at, a.overview, a.enriched_json, a.severity_hint,
               a.story_cluster_id, a.tier,
               COALESCE(uas.is_read, 0)  AS is_read,
               COALESCE(uas.is_saved, 0) AS is_saved
          FROM all_articles a
          LEFT JOIN main.feeds f ON f.id = a.feed_id
          LEFT JOIN main.user_article_state uas
                 ON uas.article_id = a.id AND uas.user_id = ?
         WHERE a.id = ?
        """,
        (user.id, article_id),
    ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found")

    enriched = json.loads(row["enriched_json"]) if row["enriched_json"] else None
    if enriched and "entities" in enriched:
        # Decorate MITRE IDs with their canonical attack.mitre.org URLs so the
        # frontend can render each as a deep link without re-implementing the
        # URL scheme.
        ent = enriched["entities"]
        ent["mitre_links"] = {
            "groups":   {g: mitre.attack_url(g) for g in ent.get("mitre_groups", [])},
            "software": {s: mitre.attack_url(s) for s in ent.get("mitre_software", [])},
            "techniques": {
                t: mitre.attack_url(t) for t in ent.get("ttps_mitre", [])
            },
            "tactics":  {t: mitre.attack_url(t) for t in ent.get("mitre_tactics", [])},
        }
    return ArticleDetail(
        id=row["id"], feed_id=row["feed_id"], feed_title=row["feed_title"],
        url=row["url"], title=row["title"], author=row["author"],
        published_at=row["published_at"], overview=row["overview"],
        enriched=enriched, severity_hint=row["severity_hint"],
        story_cluster_id=row["story_cluster_id"],
        is_read=bool(row["is_read"]), is_saved=bool(row["is_saved"]),
        tier=row["tier"],
    )


@router.get("/{article_id}/related", response_model=RelatedResponse)
def related(article_id: int,
            limit: int = 25,
            _: CurrentUser = Depends(get_current_user),
            conn: sqlite3.Connection = Depends(get_db)) -> RelatedResponse:
    base = conn.execute(
        "SELECT id, story_cluster_id FROM all_articles WHERE id = ?",
        (article_id,),
    ).fetchone()
    if not base:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found")

    cluster_id = base["story_cluster_id"]
    if cluster_id is None:
        return RelatedResponse(article_id=article_id, cluster_id=None, members=[])

    base_tokens = _fetch_tokens(conn, article_id)

    rows = conn.execute(
        """
        SELECT a.id, f.title AS feed_title, a.url, a.title,
               a.published_at, a.overview
          FROM all_articles a
          LEFT JOIN main.feeds f ON f.id = a.feed_id
         WHERE a.story_cluster_id = ? AND a.id != ?
         ORDER BY a.published_at DESC NULLS LAST
         LIMIT ?
        """,
        (cluster_id, article_id, limit),
    ).fetchall()

    members: list[RelatedArticle] = []
    for r in rows:
        sib_tokens = _fetch_tokens(conn, r["id"])
        sim = weighted_jaccard(base_tokens, sib_tokens)
        st = shared_tokens(base_tokens, sib_tokens)
        members.append(
            RelatedArticle(
                id=r["id"], feed_title=r["feed_title"], url=r["url"],
                title=r["title"], published_at=r["published_at"],
                overview=r["overview"], similarity=round(sim, 4),
                shared_tokens=st,
            )
        )
    members.sort(key=lambda m: m.similarity, reverse=True)
    return RelatedResponse(article_id=article_id, cluster_id=cluster_id, members=members)


# ---------------------------------------------------------------------------
# Read / saved state
# ---------------------------------------------------------------------------
class StateUpdate(BaseModel):
    is_read: bool | None = None
    is_saved: bool | None = None


@router.post("/{article_id}/state")
def update_state(article_id: int, data: StateUpdate,
                 user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> dict:
    exists = conn.execute(
        "SELECT 1 FROM all_articles WHERE id = ?", (article_id,)
    ).fetchone()
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found")

    now = datetime.now(timezone.utc)
    cur = conn.execute(
        "SELECT is_read, is_saved FROM main.user_article_state "
        "WHERE user_id = ? AND article_id = ?",
        (user.id, article_id),
    ).fetchone()
    is_read = cur["is_read"] if cur else 0
    is_saved = cur["is_saved"] if cur else 0
    if data.is_read is not None:
        is_read = 1 if data.is_read else 0
    if data.is_saved is not None:
        is_saved = 1 if data.is_saved else 0
    conn.execute(
        "INSERT OR REPLACE INTO main.user_article_state "
        "(user_id, article_id, is_read, is_saved, read_at, saved_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            user.id, article_id, is_read, is_saved,
            now if is_read else None,
            now if is_saved else None,
        ),
    )
    conn.commit()
    return {"is_read": bool(is_read), "is_saved": bool(is_saved)}
