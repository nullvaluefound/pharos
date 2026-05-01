"""Report-generation API.

POST /reports/generate -- build a report inline (sync) and persist it
GET  /reports          -- list the user's saved reports (most-recent first)
GET  /reports/{id}     -- fetch one report (full markdown body)
DELETE /reports/{id}   -- delete a report
POST /reports/preview  -- count articles that would feed a report without
                          calling OpenAI (useful for the form's "scope" hint)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...reports import (
    MAX_ARTICLES,
    ReportRequest,
    collect_articles,
    count_articles_in_scope,
    estimate_cost,
    generate_report,
)
from ...reports.prompts import length_targets
from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/reports", tags=["reports"])
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
StructureKind = Literal["BLUF", "custom"]
Audience = Literal["executive", "technical", "both"]
LengthKind = Literal["short", "medium", "long"]


class ReportGenerateIn(BaseModel):
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


class ReportListItem(BaseModel):
    id: int
    name: str
    audience: str
    structure_kind: str
    length_target: str
    article_count: int
    status: str
    cost_usd: float | None
    model: str | None
    created_at: str
    completed_at: str | None


class ReportDetail(ReportListItem):
    body_md: str
    request: dict
    article_ids: list[int]
    error: str | None


class ReportPreviewOut(BaseModel):
    article_count: int                  # true total in scope (uncapped)
    used_count: int                     # min(article_count, MAX_ARTICLES)
    cap: int                            # MAX_ARTICLES
    capped: bool                        # True iff article_count > cap
    sample: list[dict]
    estimated_cost_usd: float


def _to_dataclass(p: ReportGenerateIn) -> ReportRequest:
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
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=list[ReportListItem])
def list_reports(user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> list[ReportListItem]:
    rows = conn.execute(
        """
        SELECT id, name, audience, structure_kind, length_target,
               article_count, status, cost_usd, model, created_at, completed_at
          FROM reports
         WHERE user_id = ?
         ORDER BY created_at DESC
         LIMIT 200
        """,
        (user.id,),
    ).fetchall()
    return [ReportListItem(**dict(r)) for r in rows]


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(report_id: int,
               user: CurrentUser = Depends(get_current_user),
               conn: sqlite3.Connection = Depends(get_db)) -> ReportDetail:
    row = conn.execute(
        """
        SELECT id, name, audience, structure_kind, length_target,
               article_count, status, cost_usd, model, created_at, completed_at,
               body_md, request_json, article_ids_json, error
          FROM reports
         WHERE id = ? AND user_id = ?
        """,
        (report_id, user.id),
    ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    d = dict(row)
    d["request"] = json.loads(d.pop("request_json") or "{}")
    d["article_ids"] = json.loads(d.pop("article_ids_json") or "[]")
    return ReportDetail(**d)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: int,
                  user: CurrentUser = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)) -> None:
    cur = conn.execute(
        "DELETE FROM reports WHERE id = ? AND user_id = ?",
        (report_id, user.id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")


@router.post("/preview", response_model=ReportPreviewOut)
def preview_report(data: ReportGenerateIn,
                   user: CurrentUser = Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)) -> ReportPreviewOut:
    """Tell the user how many articles their filter would pull and rough
    cost, without spending any OpenAI credit.

    ``article_count`` is the TRUE total of articles matching the filter
    (uncapped). ``used_count`` is what the report will actually consume
    (capped at MAX_ARTICLES). Cost is estimated against ``used_count``
    so the displayed cost is what the user will actually be charged.
    """
    req = _to_dataclass(data)
    total = count_articles_in_scope(conn, user_id=user.id, req=req)
    used = min(total, MAX_ARTICLES)

    # Pull a small sample for display only; cap at 8 to keep the response light.
    sample_rows = collect_articles(conn, user_id=user.id, req=req, limit=8)
    sample = [
        {
            "id": r["id"],
            "title": r["title"],
            "url": r["url"],
            "feed_title": r.get("feed_title"),
            "published_at": r["published_at"],
            "severity_hint": r.get("severity_hint"),
        }
        for r in sample_rows
    ]

    # Cost heuristic: each article block ~250 input tokens + ~600 token
    # system prompt. Output bounded by length target. Half the output
    # ceiling is a reasonable mean for what the model actually emits.
    est_input = 600 + used * 250
    _, _, est_output = length_targets(data.length)
    est_cost = estimate_cost(est_input, est_output // 2)

    return ReportPreviewOut(
        article_count=total,
        used_count=used,
        cap=MAX_ARTICLES,
        capped=total > MAX_ARTICLES,
        sample=sample,
        estimated_cost_usd=round(est_cost, 4),
    )


@router.post("/generate", response_model=ReportDetail,
             status_code=status.HTTP_201_CREATED)
async def generate(data: ReportGenerateIn,
                   user: CurrentUser = Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)) -> ReportDetail:
    """Generate + persist a report inline. Blocks until OpenAI returns.

    Typical wall time at gpt-4o for a "short" report on ~50 articles is
    20-45 seconds. The frontend should show a generation spinner.
    """
    req = _to_dataclass(data)

    # Insert a pending row so we have an id to return on failure too.
    cur = conn.execute(
        """
        INSERT INTO reports (user_id, name, request_json, structure_kind,
                             audience, length_target, status)
        VALUES (?, ?, ?, ?, ?, ?, 'generating')
        """,
        (
            user.id, data.name, json.dumps(data.model_dump()),
            data.structure_kind, data.audience, data.length,
        ),
    )
    conn.commit()
    report_id = int(cur.lastrowid)

    try:
        result = await generate_report(user_id=user.id, conn=conn, req=req)
    except Exception as exc:
        log.warning("report %s generation failed: %s", report_id, exc)
        conn.execute(
            "UPDATE reports SET status = 'failed', error = ?, "
            "completed_at = ? WHERE id = ?",
            (str(exc)[:1000], datetime.now(timezone.utc), report_id),
        )
        conn.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Report generation failed: {exc}",
        )

    conn.execute(
        """
        UPDATE reports
           SET status = 'ready',
               body_md = ?,
               article_ids_json = ?,
               article_count = ?,
               cost_usd = ?,
               model = ?,
               completed_at = ?
         WHERE id = ?
        """,
        (
            result.body_md,
            json.dumps(result.article_ids),
            result.article_count,
            result.cost_usd,
            result.model,
            datetime.now(timezone.utc),
            report_id,
        ),
    )
    conn.commit()

    row = conn.execute(
        """
        SELECT id, name, audience, structure_kind, length_target,
               article_count, status, cost_usd, model, created_at, completed_at,
               body_md, request_json, article_ids_json, error
          FROM reports WHERE id = ?
        """,
        (report_id,),
    ).fetchone()
    d = dict(row)
    d["request"] = json.loads(d.pop("request_json") or "{}")
    d["article_ids"] = json.loads(d.pop("article_ids_json") or "[]")
    return ReportDetail(**d)
