"""Watches: saved searches that the user can return to (or be alerted on)."""
from __future__ import annotations

import base64
import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/watches", tags=["watches"])

# Bumped on any breaking change to the share-code envelope. Importers
# refuse anything they don't recognize.
SHARE_FORMAT_KIND = "pharos.watch"
SHARE_FORMAT_VERSION = 1

# Belt-and-suspenders limits so a malicious paste can't allocate forever.
# Real watches are ~hundreds of bytes; 64 KB is a generous ceiling.
MAX_SHARE_CODE_BYTES = 64 * 1024
MAX_QUERY_KEYS = 32
MAX_NAME_LEN = 120


class WatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: dict[str, Any]
    notify: bool = False
    # When true and the user has a notification email configured, the
    # watch checker emails a digest every time new articles match.
    # Independent of `notify` (which only controls in-app bells).
    notify_email: bool = False


class WatchOut(BaseModel):
    id: int
    name: str
    query: dict[str, Any]
    notify: bool
    notify_email: bool
    created_at: str


def _row_to_watch(r: sqlite3.Row) -> WatchOut:
    # `notify_email` is added by migration 0004; fall back to 0 so the
    # API stays usable on a DB that hasn't migrated yet.
    keys = r.keys() if hasattr(r, "keys") else []
    notify_email = bool(r["notify_email"]) if "notify_email" in keys else False
    return WatchOut(
        id=r["id"],
        name=r["name"],
        query=json.loads(r["query_json"]),
        notify=bool(r["notify"]),
        notify_email=notify_email,
        created_at=r["created_at"],
    )


@router.get("", response_model=list[WatchOut])
def list_watches(user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> list[WatchOut]:
    rows = conn.execute(
        "SELECT id, name, query_json, notify, notify_email, created_at "
        "FROM main.saved_searches WHERE user_id = ? ORDER BY created_at DESC",
        (user.id,),
    ).fetchall()
    return [_row_to_watch(r) for r in rows]


@router.post("", response_model=WatchOut, status_code=status.HTTP_201_CREATED)
def create_watch(data: WatchIn,
                 user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> WatchOut:
    cur = conn.execute(
        "INSERT INTO main.saved_searches "
        "(user_id, name, query_json, notify, notify_email) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            user.id, data.name, json.dumps(data.query),
            1 if data.notify else 0,
            1 if data.notify_email else 0,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, name, query_json, notify, notify_email, created_at "
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
        "UPDATE main.saved_searches "
        "SET name = ?, query_json = ?, notify = ?, notify_email = ? "
        "WHERE id = ? AND user_id = ?",
        (
            data.name, json.dumps(data.query),
            1 if data.notify else 0,
            1 if data.notify_email else 0,
            watch_id, user.id,
        ),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Watch not found")
    row = conn.execute(
        "SELECT id, name, query_json, notify, notify_email, created_at "
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


# ---------------------------------------------------------------------------
# Export / Import (shareable across users and across Pharos instances)
# ---------------------------------------------------------------------------
class WatchExport(BaseModel):
    """Self-describing envelope. The `code` field is base64url(JSON(envelope))
    minus the `code` itself -- it's the same payload, packed into a single
    string the user can copy/paste."""
    kind: str
    version: int
    name: str
    query: dict[str, Any]
    code: str


class WatchImportIn(BaseModel):
    """Either provide ``code`` (paste a share string) or ``data`` (raw JSON
    envelope, e.g. uploaded from a .json file). Optional ``name_override``
    lets the importer rename on the way in -- useful when the source watch's
    name collides with an existing one."""
    code: str | None = None
    data: dict[str, Any] | None = None
    name_override: str | None = Field(default=None, max_length=MAX_NAME_LEN)


def _encode_envelope(name: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Build the JSON envelope and matching base64url share code."""
    env = {
        "kind": SHARE_FORMAT_KIND,
        "version": SHARE_FORMAT_VERSION,
        "name": name,
        "query": query,
    }
    raw = json.dumps(env, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    code = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return env, code


def _decode_envelope(code: str) -> dict[str, Any]:
    """Decode a share code back into its envelope dict, with strict
    validation. Raises HTTPException on any malformedness."""
    if len(code) > MAX_SHARE_CODE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Share code too large",
        )
    s = code.strip()
    # Tolerate accidental whitespace / line wrapping that some chat
    # clients introduce on copy/paste.
    s = "".join(s.split())
    # Re-pad so urlsafe_b64decode is happy without strict padding.
    pad = (-len(s)) % 4
    s = s + ("=" * pad)
    try:
        raw = base64.urlsafe_b64decode(s.encode("ascii"))
    except Exception:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Share code is not valid base64url",
        )
    try:
        env = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Share code did not decode to valid JSON",
        )
    if not isinstance(env, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Share code envelope must be a JSON object",
        )
    return env


def _validate_envelope(env: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Validate an envelope dict and return ``(name, query)``."""
    if env.get("kind") != SHARE_FORMAT_KIND:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Not a {SHARE_FORMAT_KIND} payload",
        )
    if env.get("version") != SHARE_FORMAT_VERSION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported share format version: {env.get('version')!r} "
            f"(this Pharos understands v{SHARE_FORMAT_VERSION})",
        )
    name = env.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing or empty name")
    name = name.strip()[:MAX_NAME_LEN]

    query = env.get("query")
    if not isinstance(query, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "query must be an object")
    if len(query) > MAX_QUERY_KEYS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"query has too many keys (max {MAX_QUERY_KEYS})",
        )
    return name, query


def _unique_name(conn: sqlite3.Connection, user_id: int, base: str) -> str:
    """Return ``base`` if not already taken by this user, else suffix it
    with ` (imported)` / ` (imported 2)` until unique."""
    existing = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM main.saved_searches WHERE user_id = ?", (user_id,)
        )
    }
    if base not in existing:
        return base
    candidate = f"{base} (imported)"
    if candidate not in existing:
        return candidate
    n = 2
    while f"{base} (imported {n})" in existing:
        n += 1
    return f"{base} (imported {n})"


@router.get("/{watch_id}/export", response_model=WatchExport)
def export_watch(watch_id: int,
                 user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> WatchExport:
    """Export one of the caller's watches as a portable share envelope.

    The watch's filter criteria are not secret (entity names, keywords,
    timeframe). The ``notify`` flag is intentionally NOT exported -- each
    importer decides whether they want notifications themselves."""
    row = conn.execute(
        "SELECT name, query_json FROM main.saved_searches "
        "WHERE id = ? AND user_id = ?",
        (watch_id, user.id),
    ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Watch not found")
    query = json.loads(row["query_json"])
    env, code = _encode_envelope(row["name"], query)
    return WatchExport(
        kind=env["kind"],
        version=env["version"],
        name=env["name"],
        query=env["query"],
        code=code,
    )


@router.post(
    "/import",
    response_model=WatchOut,
    status_code=status.HTTP_201_CREATED,
)
def import_watch(data: WatchImportIn,
                 user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> WatchOut:
    """Import a watch from a share code or a raw JSON envelope.

    Notify is always set to ``False`` on import; the importing user can
    flip it on themselves once they've reviewed the watch."""
    if not data.code and not data.data:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Provide either `code` or `data`",
        )
    env = data.data if data.data else _decode_envelope(data.code or "")
    name, query = _validate_envelope(env)
    if data.name_override and data.name_override.strip():
        name = data.name_override.strip()[:MAX_NAME_LEN]
    final_name = _unique_name(conn, user.id, name)

    cur = conn.execute(
        "INSERT INTO main.saved_searches "
        "(user_id, name, query_json, notify, notify_email) "
        "VALUES (?, ?, ?, 0, 0)",
        (user.id, final_name, json.dumps(query)),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, name, query_json, notify, notify_email, created_at "
        "FROM main.saved_searches WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return _row_to_watch(row)
