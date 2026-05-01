"""Auth routes: login and (optionally) self-registration."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from ...config import get_settings
from ..auth import authenticate, create_user, issue_token
from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class RegisterIn(LoginIn):
    pass


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    is_admin: bool


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, response: Response,
          conn: sqlite3.Connection = Depends(get_db)) -> TokenOut:
    row = authenticate(conn, username=data.username, password=data.password)
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = issue_token(
        user_id=row["id"], username=row["username"], is_admin=bool(row["is_admin"])
    )
    response.set_cookie(
        "pharos_token", token, httponly=True, samesite="lax",
        max_age=get_settings().jwt_ttl_seconds,
    )
    return TokenOut(
        access_token=token, user_id=row["id"], username=row["username"],
        is_admin=bool(row["is_admin"]),
    )


@router.post("/register", response_model=TokenOut)
def register(data: RegisterIn, response: Response,
             conn: sqlite3.Connection = Depends(get_db)) -> TokenOut:
    if not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration disabled")
    existing = conn.execute(
        "SELECT id FROM users WHERE username = ?", (data.username,)
    ).fetchone()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    uid = create_user(conn, username=data.username, password=data.password)
    conn.commit()
    token = issue_token(user_id=uid, username=data.username, is_admin=False)
    response.set_cookie(
        "pharos_token", token, httponly=True, samesite="lax",
        max_age=get_settings().jwt_ttl_seconds,
    )
    return TokenOut(access_token=token, user_id=uid, username=data.username, is_admin=False)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie("pharos_token")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin}
