"""Recurring report schedules.

Each schedule is a saved ReportRequest plus a cadence (daily / weekly /
monthly). The notifier worker fires due schedules on its tick; these
routes are pure CRUD + a "run now" hatch that just nudges next_run_at.

POST /report-schedules            -- create
GET  /report-schedules            -- list (caller's only)
GET  /report-schedules/{id}       -- fetch one
PUT  /report-schedules/{id}       -- update (recomputes next_run_at)
DELETE /report-schedules/{id}     -- delete
POST /report-schedules/{id}/run-now  -- bump next_run_at to now()
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...notifier import email as mailer
from ...reports import initialize_next_run_at
from ...reports.generator import ReportRequest
from ...reports.scheduler import persist_request_json, trigger_now
from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/report-schedules", tags=["reports"])
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
Cadence = Literal["daily", "weekly", "monthly"]
StructureKind = Literal["BLUF", "custom"]
Audience = Literal["executive", "technical", "both"]
LengthKind = Literal["short", "medium", "long"]


class ScheduleRequestPayload(BaseModel):
    """The frozen ReportRequest a schedule will run each cadence.

    Mirror of routes/reports.py:ReportGenerateIn so the frontend can reuse
    the same form. We split the validation here so the schedule routes
    don't import the reports router (avoids circular plumbing).
    """
    name: str = Field(min_length=1, max_length=200)
    keywords: list[str] = Field(default_factory=list)
    since_days: int = Field(default=14, ge=1, le=365)
    feed_ids: list[int] | None = None
    any_of: dict[str, list[str]] = Field(default_factory=dict)
    all_of: dict[str, list[str]] = Field(default_factory=dict)
    has_entity_types: list[str] = Field(default_factory=list)
    structure_kind: StructureKind = "BLUF"
    sections: list[str] = Field(default_factory=list)
    audience: Audience = "both"
    length: LengthKind = "short"
    scope_note: str = ""


class ScheduleIn(BaseModel):
    """Request body for create/update."""
    name: str = Field(min_length=1, max_length=200)
    request: ScheduleRequestPayload
    cadence: Cadence
    hour_utc: int = Field(ge=0, le=23, default=13)
    # Required for `weekly`, ignored otherwise. 0=Mon..6=Sun.
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    # Required for `monthly`, ignored otherwise. 1..28 (intentionally
    # capped so every month is valid -- no "Feb 30 is implied as Mar 2"
    # surprises).
    day_of_month: int | None = Field(default=None, ge=1, le=28)
    email_to: str | None = Field(default=None, max_length=320)
    active: bool = True


class ScheduleOut(BaseModel):
    id: int
    name: str
    request: dict
    cadence: str
    hour_utc: int
    day_of_week: int | None
    day_of_month: int | None
    email_to: str | None
    active: bool
    next_run_at: str | None
    last_run_at: str | None
    last_report_id: int | None
    last_error: str | None
    created_at: str


class ScheduleListItem(ScheduleOut):
    """List rows include the same fields as ScheduleOut today; this alias
    keeps the door open for trimming list fields later without breaking
    the frontend type."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_out(row: sqlite3.Row) -> ScheduleOut:
    return ScheduleOut(
        id=int(row["id"]),
        name=row["name"],
        request=json.loads(row["request_json"] or "{}"),
        cadence=row["cadence"],
        hour_utc=int(row["hour_utc"]),
        day_of_week=row["day_of_week"],
        day_of_month=row["day_of_month"],
        email_to=row["email_to"],
        active=bool(row["active"]),
        next_run_at=row["next_run_at"],
        last_run_at=row["last_run_at"],
        last_report_id=row["last_report_id"],
        last_error=row["last_error"],
        created_at=row["created_at"],
    )


def _validate_cadence_fields(data: ScheduleIn) -> None:
    if data.cadence == "weekly" and data.day_of_week is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Weekly schedules require day_of_week (0=Mon..6=Sun).",
        )
    if data.cadence == "monthly" and data.day_of_month is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Monthly schedules require day_of_month (1..28).",
        )
    if data.email_to:
        if not mailer.is_valid_email(data.email_to.strip()):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "email_to is not a valid email address.",
            )


def _to_request_dataclass(p: ScheduleRequestPayload) -> ReportRequest:
    return ReportRequest(
        name=p.name,
        keywords=p.keywords,
        since_days=p.since_days,
        feed_ids=p.feed_ids,
        any_of=p.any_of,
        all_of=p.all_of,
        has_entity_types=p.has_entity_types,
        structure_kind=p.structure_kind,
        sections=p.sections,
        audience=p.audience,
        length=p.length,
        scope_note=p.scope_note,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("", response_model=list[ScheduleListItem])
def list_schedules(user: CurrentUser = Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)) -> list[ScheduleListItem]:
    rows = conn.execute(
        """
        SELECT id, user_id, name, request_json, cadence, hour_utc,
               day_of_week, day_of_month, email_to, active,
               next_run_at, last_run_at, last_report_id, last_error,
               created_at
          FROM report_schedules
         WHERE user_id = ?
         ORDER BY active DESC, next_run_at ASC NULLS LAST, created_at DESC
        """,
        (user.id,),
    ).fetchall()
    return [_row_to_out(r) for r in rows]


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(data: ScheduleIn,
                    user: CurrentUser = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)) -> ScheduleOut:
    _validate_cadence_fields(data)

    next_run_at = (
        initialize_next_run_at(
            cadence=data.cadence,
            hour_utc=data.hour_utc,
            day_of_week=data.day_of_week,
            day_of_month=data.day_of_month,
        ) if data.active else None
    )
    cur = conn.execute(
        """
        INSERT INTO report_schedules
            (user_id, name, request_json, cadence, hour_utc,
             day_of_week, day_of_month, email_to, active, next_run_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user.id,
            data.name,
            persist_request_json(_to_request_dataclass(data.request)),
            data.cadence,
            data.hour_utc,
            data.day_of_week,
            data.day_of_month,
            (data.email_to or None) and data.email_to.strip(),
            1 if data.active else 0,
            next_run_at,
        ),
    )
    conn.commit()
    return _fetch_one(conn, int(cur.lastrowid), user.id)


@router.get("/{schedule_id}", response_model=ScheduleOut)
def get_schedule(schedule_id: int,
                 user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> ScheduleOut:
    return _fetch_one(conn, schedule_id, user.id)


@router.put("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: int,
                    data: ScheduleIn,
                    user: CurrentUser = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)) -> ScheduleOut:
    _validate_cadence_fields(data)
    # Recompute next_run_at on any edit -- the cadence / hour / day might
    # have changed, and even if it hasn't, recomputing is harmless.
    next_run_at = (
        initialize_next_run_at(
            cadence=data.cadence,
            hour_utc=data.hour_utc,
            day_of_week=data.day_of_week,
            day_of_month=data.day_of_month,
        ) if data.active else None
    )
    cur = conn.execute(
        """
        UPDATE report_schedules
           SET name = ?,
               request_json = ?,
               cadence = ?,
               hour_utc = ?,
               day_of_week = ?,
               day_of_month = ?,
               email_to = ?,
               active = ?,
               next_run_at = ?
         WHERE id = ? AND user_id = ?
        """,
        (
            data.name,
            persist_request_json(_to_request_dataclass(data.request)),
            data.cadence,
            data.hour_utc,
            data.day_of_week,
            data.day_of_month,
            (data.email_to or None) and data.email_to.strip(),
            1 if data.active else 0,
            next_run_at,
            schedule_id,
            user.id,
        ),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    return _fetch_one(conn, schedule_id, user.id)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(schedule_id: int,
                    user: CurrentUser = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)) -> None:
    cur = conn.execute(
        "DELETE FROM report_schedules WHERE id = ? AND user_id = ?",
        (schedule_id, user.id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")


@router.post("/{schedule_id}/run-now", response_model=ScheduleOut)
def run_now(schedule_id: int,
            user: CurrentUser = Depends(get_current_user),
            conn: sqlite3.Connection = Depends(get_db)) -> ScheduleOut:
    """Bump ``next_run_at`` to now so the next notifier tick fires this
    schedule. Returns the updated row -- the actual report shows up in
    /reports once the worker tick completes (~60s)."""
    try:
        trigger_now(conn, schedule_id, user.id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    return _fetch_one(conn, schedule_id, user.id)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _fetch_one(conn: sqlite3.Connection, schedule_id: int, user_id: int) -> ScheduleOut:
    row = conn.execute(
        """
        SELECT id, user_id, name, request_json, cadence, hour_utc,
               day_of_week, day_of_month, email_to, active,
               next_run_at, last_run_at, last_report_id, last_error,
               created_at
          FROM report_schedules
         WHERE id = ? AND user_id = ?
        """,
        (schedule_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    return _row_to_out(row)
