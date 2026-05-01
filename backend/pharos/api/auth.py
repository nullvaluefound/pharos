"""Authentication helpers: password hashing and JWT issuance."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from ..config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except ValueError:
        return False


def create_user(conn: sqlite3.Connection, *, username: str, password: str,
                is_admin: bool = False) -> int:
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
        (username, hash_password(password), 1 if is_admin else 0),
    )
    return int(cur.lastrowid)


def authenticate(conn: sqlite3.Connection, *, username: str, password: str) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT id, username, password_hash, is_admin FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return row


def issue_token(*, user_id: int, username: str, is_admin: bool) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "uname": username,
        "adm": bool(is_admin),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=s.jwt_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError:
        return None
