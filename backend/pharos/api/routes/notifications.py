"""In-app notifications. Driven by the watch checker (separate job)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


class Notification(BaseModel):
    id: int
    watch_id: int | None
    watch_name: str | None
    article_id: int | None
    title: str
    body: str | None
    is_read: bool
    created_at: str


class NotificationList(BaseModel):
    items: list[Notification]
    unread_count: int


@router.get("", response_model=NotificationList)
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> NotificationList:
    where = ["n.user_id = ?"]
    params: list = [user.id]
    if unread_only:
        where.append("n.is_read = 0")
    sql = f"""
        SELECT n.id, n.watch_id, w.name AS watch_name, n.article_id,
               n.title, n.body, n.is_read, n.created_at
          FROM notifications n
          LEFT JOIN saved_searches w ON w.id = n.watch_id
         WHERE {' AND '.join(where)}
         ORDER BY n.created_at DESC
         LIMIT ?
    """
    rows = conn.execute(sql, (*params, limit)).fetchall()
    unread = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
        (user.id,),
    ).fetchone()["c"]
    return NotificationList(
        items=[
            Notification(
                id=r["id"],
                watch_id=r["watch_id"],
                watch_name=r["watch_name"],
                article_id=r["article_id"],
                title=r["title"],
                body=r["body"],
                is_read=bool(r["is_read"]),
                created_at=r["created_at"],
            )
            for r in rows
        ],
        unread_count=int(unread or 0),
    )


@router.post("/{notification_id}/read", status_code=status.HTTP_200_OK)
def mark_read(notification_id: int,
              user: CurrentUser = Depends(get_current_user),
              conn: sqlite3.Connection = Depends(get_db)) -> dict:
    cur = conn.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, user.id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    return {"ok": True}


@router.post("/read-all", status_code=status.HTTP_200_OK)
def mark_all_read(user: CurrentUser = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)) -> dict:
    cur = conn.execute(
        "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
        (user.id,),
    )
    conn.commit()
    return {"ok": True, "updated": cur.rowcount}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notification_id: int,
                        user: CurrentUser = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db)) -> None:
    cur = conn.execute(
        "DELETE FROM notifications WHERE id = ? AND user_id = ?",
        (notification_id, user.id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
