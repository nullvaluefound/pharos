"""Watches: saved searches that the user can return to (or be alerted on)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/watches", tags=["watches"])


class WatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: dict[str, Any]
    notify: bool = False


class WatchOut(BaseModel):
    id: int
    name: str
    query: dict[str, Any]
    notify: bool
    created_at: str


def _row_to_watch(r: sqlite3.Row) -> WatchOut:
    return WatchOut(
        id=r["id"],
        name=r["name"],
        query=json.loads(r["query_json"]),
        notify=bool(r["notify"]),
        created_at=r["created_at"],
    )


@router.get("", response_model=list[WatchOut])
def list_watches(user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> list[WatchOut]:
    rows = conn.execute(
        "SELECT id, name, query_json, notify, created_at "
        "FROM main.saved_searches WHERE user_id = ? ORDER BY created_at DESC",
        (user.id,),
    ).fetchall()
    return [_row_to_watch(r) for r in rows]


@router.post("", response_model=WatchOut, status_code=status.HTTP_201_CREATED)
def create_watch(data: WatchIn,
                 user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> WatchOut:
    cur = conn.execute(
        "INSERT INTO main.saved_searches (user_id, name, query_json, notify) "
        "VALUES (?, ?, ?, ?)",
        (user.id, data.name, json.dumps(data.query), 1 if data.notify else 0),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, name, query_json, notify, created_at "
        "FROM main.saved_searches WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return _row_to_watch(row)


@router.put("/{watch_id}", response_model=WatchOut)
def update_watch(watch_id: int,
                 data: WatchIn,
                 user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> WatchOut:
    cur = conn.execute(
        "UPDATE main.saved_searches SET name = ?, query_json = ?, notify = ? "
        "WHERE id = ? AND user_id = ?",
        (data.name, json.dumps(data.query), 1 if data.notify else 0,
         watch_id, user.id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Watch not found")
    row = conn.execute(
        "SELECT id, name, query_json, notify, created_at "
        "FROM main.saved_searches WHERE id = ?",
        (watch_id,),
    ).fetchone()
    return _row_to_watch(row)


@router.delete("/{watch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watch(watch_id: int,
                 user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> None:
    cur = conn.execute(
        "DELETE FROM main.saved_searches WHERE id = ? AND user_id = ?",
        (watch_id, user.id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Watch not found")
