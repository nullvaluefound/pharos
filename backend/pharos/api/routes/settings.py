"""User settings: change password, manage UI preferences."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import hash_password, verify_password
from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/settings", tags=["settings"])


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


class PreferencesIn(BaseModel):
    settings: dict = Field(default_factory=dict)


class PreferencesOut(BaseModel):
    settings: dict


@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(user: CurrentUser = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)) -> PreferencesOut:
    row = conn.execute(
        "SELECT settings_json FROM users WHERE id = ?", (user.id,),
    ).fetchone()
    raw = row["settings_json"] if row else "{}"
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {}
    return PreferencesOut(settings=data)


@router.put("/preferences", response_model=PreferencesOut)
def update_preferences(data: PreferencesIn,
                       user: CurrentUser = Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db)) -> PreferencesOut:
    conn.execute(
        "UPDATE users SET settings_json = ? WHERE id = ?",
        (json.dumps(data.settings), user.id),
    )
    conn.commit()
    return PreferencesOut(settings=data.settings)


@router.post("/password", status_code=status.HTTP_200_OK)
def change_password(data: PasswordChange,
                    user: CurrentUser = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)) -> dict:
    row = conn.execute(
        "SELECT password_hash FROM users WHERE id = ?", (user.id,),
    ).fetchone()
    if not row or not verify_password(data.current_password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect")
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(data.new_password), user.id),
    )
    conn.commit()
    return {"ok": True}
