"""Recurring report scheduler.

Watches the ``report_schedules`` table for rows whose ``next_run_at`` has
elapsed, runs the saved ReportRequest through ``generate_report``, persists
the result as a regular ``reports`` row, optionally emails it to the user,
and recomputes ``next_run_at`` for the following cadence.

Hot-loop integration
--------------------
This module exposes a single async entry point, :func:`run_due_schedules`,
that the notifier loop calls once per tick. We keep it inside the same
process to avoid adding a new container/supervisor program for what is
ultimately one SQL scan plus an occasional LLM call.

Design notes
------------
* All scheduling math is done in **UTC**. The frontend converts to local
  time. We never store a local hour-of-day, only ``hour_utc``.
* "Monthly" is capped to day-of-month 28 in the migration so we never
  have to deal with February shenanigans.
* Picking up a due row sets ``next_run_at`` to the *next* future cadence
  *before* the LLM call. If the call fails we leave ``last_error`` set
  but we don't retry inside the same cadence -- the next scheduled run
  will get a fresh chance. This mirrors how cron behaves (one shot per
  scheduled time, however lossy).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from . import generator as report_gen
from . import email_render
from .generator import ReportRequest
from ..notifier import email as mailer

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cadence math
# ---------------------------------------------------------------------------
def compute_next_run_at(
    *,
    cadence: str,
    hour_utc: int,
    day_of_week: int | None,
    day_of_month: int | None,
    now: datetime | None = None,
) -> datetime:
    """Return the next future UTC datetime that satisfies the cadence.

    For schedules whose nominal time has already elapsed today, this
    returns the *next* occurrence (tomorrow / next week / next month),
    not "right now". A separate "run now" code path handles immediate
    execution.
    """
    now = now or datetime.now(timezone.utc)
    # Normalize to a naive-ish UTC datetime (sqlite stores naive ISO strings).
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if cadence == "daily":
        candidate = now.replace(
            hour=hour_utc, minute=0, second=0, microsecond=0,
        )
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate

    if cadence == "weekly":
        # day_of_week: 0=Monday..6=Sunday (matches Python's weekday()).
        target = day_of_week if day_of_week is not None else 0
        candidate = now.replace(
            hour=hour_utc, minute=0, second=0, microsecond=0,
        )
        delta_days = (target - candidate.weekday()) % 7
        candidate = candidate + timedelta(days=delta_days)
        if candidate <= now:
            candidate = candidate + timedelta(days=7)
        return candidate

    if cadence == "monthly":
        # day_of_month: 1..28 (migration enforces the cap).
        target_dom = day_of_month or 1
        candidate = now.replace(
            day=target_dom, hour=hour_utc, minute=0, second=0, microsecond=0,
        )
        if candidate <= now:
            # Roll to next month -- careful around year boundaries.
            month = candidate.month + 1
            year = candidate.year
            if month == 13:
                month = 1
                year += 1
            candidate = candidate.replace(year=year, month=month)
        return candidate

    raise ValueError(f"Unknown cadence: {cadence!r}")


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------
def schedule_row_to_request(row: sqlite3.Row | dict) -> ReportRequest:
    """Re-hydrate a stored request_json blob into a ReportRequest."""
    raw = row["request_json"] if not isinstance(row, dict) else row.get("request_json")
    data = json.loads(raw or "{}")
    # Filter to known fields so old rows can't crash on schema drift.
    allowed = {
        "name", "keywords", "since_days", "feed_ids",
        "any_of", "all_of", "has_entity_types",
        "structure_kind", "sections", "audience", "length", "scope_note",
    }
    payload = {k: v for k, v in data.items() if k in allowed}
    return ReportRequest(**payload)


def persist_request_json(req: ReportRequest) -> str:
    """Serialize a ReportRequest for storage."""
    return json.dumps(asdict(req))


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------
async def _run_one_schedule(conn: sqlite3.Connection, schedule: sqlite3.Row) -> None:
    """Run a single due schedule end-to-end (generate + email + bookkeeping)."""
    sched_id = int(schedule["id"])
    user_id = int(schedule["user_id"])
    sched_name = schedule["name"]
    log.info("running scheduled report id=%s user=%s name=%r",
             sched_id, user_id, sched_name)

    req = schedule_row_to_request(schedule)

    # --- 1. Bump next_run_at *before* the LLM call so a long-running
    #        generate doesn't trip a duplicate-fire if the loop ticks
    #        again mid-call.
    new_next = compute_next_run_at(
        cadence=schedule["cadence"],
        hour_utc=int(schedule["hour_utc"]),
        day_of_week=schedule["day_of_week"],
        day_of_month=schedule["day_of_month"],
    )
    conn.execute(
        "UPDATE report_schedules SET next_run_at = ?, last_run_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (new_next.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds"),
         sched_id),
    )
    conn.commit()

    # --- 2. Insert a 'generating' reports row so a partial state is visible
    #        in the UI.
    cur = conn.execute(
        """
        INSERT INTO reports (user_id, name, request_json, structure_kind,
                             audience, length_target, status)
        VALUES (?, ?, ?, ?, ?, ?, 'generating')
        """,
        (
            user_id, req.name, persist_request_json(req),
            req.structure_kind, req.audience, req.length,
        ),
    )
    conn.commit()
    report_id = int(cur.lastrowid)

    # --- 3. Generate.
    try:
        result = await report_gen.generate_report(
            user_id=user_id, conn=conn, req=req,
        )
    except Exception as exc:
        log.warning("scheduled report %s (sched=%s) failed: %s",
                    report_id, sched_id, exc)
        conn.execute(
            "UPDATE reports SET status = 'failed', error = ?, "
            "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (str(exc)[:1000], report_id),
        )
        conn.execute(
            "UPDATE report_schedules SET last_report_id = ?, last_error = ? "
            "WHERE id = ?",
            (report_id, str(exc)[:1000], sched_id),
        )
        conn.commit()
        return

    # --- 4. Persist the finished body.
    conn.execute(
        """
        UPDATE reports
           SET status = 'ready',
               body_md = ?,
               article_ids_json = ?,
               article_count = ?,
               cost_usd = ?,
               model = ?,
               completed_at = CURRENT_TIMESTAMP
         WHERE id = ?
        """,
        (
            result.body_md,
            json.dumps(result.article_ids),
            result.article_count,
            result.cost_usd,
            result.model,
            report_id,
        ),
    )
    conn.execute(
        "UPDATE report_schedules SET last_report_id = ?, last_error = NULL "
        "WHERE id = ?",
        (report_id, sched_id),
    )
    conn.commit()

    # --- 5. Optional email delivery.
    _maybe_email_scheduled_report(
        conn=conn, schedule=schedule, report_id=report_id,
        report_name=req.name, body_md=result.body_md,
        audience=req.audience, length_target=req.length,
        structure_kind=req.structure_kind,
        article_count=result.article_count,
        cost_usd=result.cost_usd,
        sched_id=sched_id,
    )


def _maybe_email_scheduled_report(
    *,
    conn: sqlite3.Connection,
    schedule: sqlite3.Row,
    report_id: int,
    report_name: str,
    body_md: str,
    audience: str,
    length_target: str,
    structure_kind: str,
    article_count: int,
    cost_usd: float,
    sched_id: int,
) -> None:
    """Send a generated report by email if there's a destination + SMTP."""
    if not mailer.is_smtp_configured():
        return

    # Prefer the schedule's explicit override; fall back to the user's
    # saved notification email.
    raw = (schedule["email_to"] or "").strip()
    if not raw:
        urow = conn.execute(
            "SELECT email FROM users WHERE id = ?",
            (int(schedule["user_id"]),),
        ).fetchone()
        raw = (urow["email"] if urow and urow["email"] else "").strip()
    if not mailer.is_valid_email(raw):
        # No-op silently; the report is still saved and visible in the UI.
        return

    try:
        subject, text, html = email_render.render_report_email(
            report_name=report_name,
            report_id=report_id,
            body_md=body_md or "",
            audience=audience,
            length_target=length_target,
            structure_kind=structure_kind,
            article_count=article_count,
            cost_usd=cost_usd,
            schedule_name=schedule["name"],
        )
        mailer.send_email(to=raw, subject=subject, text=text, html=html)
    except Exception as e:
        log.warning("scheduled report email failed (sched=%s report=%s): %s",
                    sched_id, report_id, e)
        conn.execute(
            "UPDATE report_schedules SET last_error = ? WHERE id = ?",
            (f"email: {e}"[:1000], sched_id),
        )
        conn.commit()


async def run_due_schedules(conn: sqlite3.Connection) -> int:
    """Find every active schedule whose ``next_run_at`` has elapsed and
    run it. Returns the number of schedules that fired this tick."""
    rows = conn.execute(
        """
        SELECT id, user_id, name, request_json, cadence, hour_utc,
               day_of_week, day_of_month, email_to, active,
               next_run_at, last_run_at, last_report_id
          FROM report_schedules
         WHERE active = 1
           AND next_run_at IS NOT NULL
           AND next_run_at <= CURRENT_TIMESTAMP
         ORDER BY next_run_at ASC
         LIMIT 5
        """
    ).fetchall()
    if not rows:
        return 0

    fired = 0
    for sched in rows:
        try:
            await _run_one_schedule(conn, sched)
            fired += 1
        except Exception as e:
            # _run_one_schedule already handles its own errors, but defend
            # in depth so one broken row doesn't poison the whole tick.
            log.exception("schedule loop crash on id=%s: %s", sched["id"], e)
    return fired


def initialize_next_run_at(
    *,
    cadence: str,
    hour_utc: int,
    day_of_week: int | None,
    day_of_month: int | None,
) -> str:
    """Compute the initial ``next_run_at`` (as a sqlite-friendly ISO
    string) for a freshly-created or freshly-edited schedule."""
    dt = compute_next_run_at(
        cadence=cadence,
        hour_utc=hour_utc,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
    )
    return dt.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def trigger_now(conn: sqlite3.Connection, schedule_id: int, user_id: int) -> None:
    """Move ``next_run_at`` to "now" so the next loop tick fires this
    schedule. Cheaper than spawning the LLM call inline from the request
    handler (which would block the request for ~30-60s) and survives the
    process getting kicked between request and run."""
    cur = conn.execute(
        "UPDATE report_schedules SET next_run_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND user_id = ?",
        (schedule_id, user_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise LookupError("schedule not found")
