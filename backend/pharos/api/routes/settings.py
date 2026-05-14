"""User settings: change password, manage UI preferences, configure
notification email."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import hash_password, verify_password
from ..deps import CurrentUser, get_current_user, get_db
from ...notifier import email as mailer

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


# ---------------------------------------------------------------------------
# Notification email (where digest emails go for this user)
# ---------------------------------------------------------------------------
class EmailIn(BaseModel):
    # Empty string is allowed and clears the user's email (which disables
    # email digests for them). We do shape validation in the handler.
    email: str = Field(default="", max_length=320)


class EmailStatusOut(BaseModel):
    email: str | None
    smtp_configured: bool


@router.get("/email", response_model=EmailStatusOut)
def get_notification_email(user: CurrentUser = Depends(get_current_user),
                           conn: sqlite3.Connection = Depends(get_db)) -> EmailStatusOut:
    row = conn.execute(
        "SELECT email FROM users WHERE id = ?", (user.id,),
    ).fetchone()
    return EmailStatusOut(
        email=(row["email"] if row else None) or None,
        smtp_configured=mailer.is_smtp_configured(),
    )


@router.put("/email", response_model=EmailStatusOut)
def set_notification_email(data: EmailIn,
                           user: CurrentUser = Depends(get_current_user),
                           conn: sqlite3.Connection = Depends(get_db)) -> EmailStatusOut:
    addr = (data.email or "").strip()
    if addr and not mailer.is_valid_email(addr):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That doesn't look like a valid email address")
    conn.execute(
        "UPDATE users SET email = ? WHERE id = ?",
        (addr or None, user.id),
    )
    conn.commit()
    return EmailStatusOut(
        email=addr or None,
        smtp_configured=mailer.is_smtp_configured(),
    )


@router.post("/email/test", status_code=status.HTTP_200_OK)
def send_test_email(user: CurrentUser = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Send a one-off "this works" email to the user's configured address.

    Useful for verifying SMTP credentials without waiting for a real
    watch hit. Returns 400 if the user hasn't set an email or SMTP
    isn't configured server-side; 502 if the relay rejects the message.
    """
    if not mailer.is_smtp_configured():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "SMTP is not configured on this Pharos server. Ask your "
            "administrator to set SMTP_HOST and friends in the .env file.",
        )
    row = conn.execute(
        "SELECT email FROM users WHERE id = ?", (user.id,),
    ).fetchone()
    addr = (row["email"] if row else None) or ""
    if not mailer.is_valid_email(addr):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Set a notification email first.",
        )
    try:
        mailer.send_email(
            to=addr,
            subject="[Pharos] Test notification",
            text=(
                "If you can read this, Pharos can deliver watch digests to "
                f"{addr}.\n\n"
                "You can manage which watches send email from the Watches page."
            ),
            html=(
                "<p>If you can read this, Pharos can deliver watch digests "
                f"to <b>{addr}</b>.</p>"
                "<p>You can manage which watches send email from the "
                "Watches page.</p>"
            ),
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"SMTP relay rejected the message: {e}",
        )
    return {"ok": True, "sent_to": addr}
