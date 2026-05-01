"""Bookmarks (saved articles) for the current user."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


class BookmarkOut(BaseModel):
    article_id: int
    feed_title: str | None
    url: str
    title: str | None
    overview: str | None
    saved_at: str | None
    published_at: str | None
    tier: str


@router.get("", response_model=list[BookmarkOut])
def list_bookmarks(limit: int = Query(default=100, ge=1, le=500),
                   user: CurrentUser = Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)) -> list[BookmarkOut]:
    rows = conn.execute(
        """
        SELECT uas.article_id, f.title AS feed_title, a.url, a.title, a.overview,
               uas.saved_at, a.published_at, a.tier
          FROM main.user_article_state uas
          JOIN all_articles a ON a.id = uas.article_id
          LEFT JOIN main.feeds f ON f.id = a.feed_id
         WHERE uas.user_id = ? AND uas.is_saved = 1
         ORDER BY uas.saved_at DESC
         LIMIT ?
        """,
        (user.id, limit),
    ).fetchall()
    return [BookmarkOut(**dict(r)) for r in rows]
