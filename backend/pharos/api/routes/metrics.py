"""Metrics & insights: aggregate views over the user's enriched corpus."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/metrics", tags=["metrics"])


class EntityCount(BaseModel):
    type: str
    name: str
    display_name: str
    count: int


class TimeBucket(BaseModel):
    bucket: str
    count: int


class OverviewResponse(BaseModel):
    article_count: int
    enriched_count: int
    pending_count: int
    cluster_count: int
    feed_count: int
    saved_count: int
    days: int


class TopEntitiesResponse(BaseModel):
    entities: list[EntityCount]


class TimeseriesResponse(BaseModel):
    buckets: list[TimeBucket]


class SeverityBreakdown(BaseModel):
    severity: str | None
    count: int


class SeverityResponse(BaseModel):
    breakdown: list[SeverityBreakdown]


def _user_article_filter(days: int) -> tuple[str, list[Any]]:
    return (
        "JOIN main.subscriptions s ON s.feed_id = a.feed_id "
        "WHERE s.user_id = ? AND a.published_at > datetime('now', ?)",
        [f"-{days} days"],
    )


@router.get("/overview", response_model=OverviewResponse)
def overview(days: int = Query(default=30, ge=1, le=365),
             user: CurrentUser = Depends(get_current_user),
             conn: sqlite3.Connection = Depends(get_db)) -> OverviewResponse:
    article_total = conn.execute(
        "SELECT COUNT(*) AS c FROM all_articles a "
        "JOIN main.subscriptions s ON s.feed_id = a.feed_id "
        "WHERE s.user_id = ? AND a.published_at > datetime('now', ?)",
        (user.id, f"-{days} days"),
    ).fetchone()["c"]
    enriched = conn.execute(
        "SELECT COUNT(*) AS c FROM all_articles a "
        "JOIN main.subscriptions s ON s.feed_id = a.feed_id "
        "WHERE s.user_id = ? AND a.enrichment_status = 'enriched' "
        "AND a.published_at > datetime('now', ?)",
        (user.id, f"-{days} days"),
    ).fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM all_articles a "
        "JOIN main.subscriptions s ON s.feed_id = a.feed_id "
        "WHERE s.user_id = ? AND a.enrichment_status IN ('pending', 'in_progress') "
        "AND a.published_at > datetime('now', ?)",
        (user.id, f"-{days} days"),
    ).fetchone()["c"]
    clusters = conn.execute(
        "SELECT COUNT(DISTINCT a.story_cluster_id) AS c FROM all_articles a "
        "JOIN main.subscriptions s ON s.feed_id = a.feed_id "
        "WHERE s.user_id = ? AND a.story_cluster_id IS NOT NULL "
        "AND a.published_at > datetime('now', ?)",
        (user.id, f"-{days} days"),
    ).fetchone()["c"]
    feeds = conn.execute(
        "SELECT COUNT(*) AS c FROM subscriptions WHERE user_id = ?", (user.id,),
    ).fetchone()["c"]
    saved = conn.execute(
        "SELECT COUNT(*) AS c FROM user_article_state WHERE user_id = ? AND is_saved = 1",
        (user.id,),
    ).fetchone()["c"]
    return OverviewResponse(
        article_count=article_total or 0,
        enriched_count=enriched or 0,
        pending_count=pending or 0,
        cluster_count=clusters or 0,
        feed_count=feeds or 0,
        saved_count=saved or 0,
        days=days,
    )


@router.get("/top-entities", response_model=TopEntitiesResponse)
def top_entities(
    type: str = Query(..., description="entity type (e.g. threat_actor, cve, sector)"),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> TopEntitiesResponse:
    rows = conn.execute(
        """
        SELECT e.type, e.canonical_name AS name, e.display_name, COUNT(*) AS c
          FROM article_entities ae
          JOIN entities e ON e.id = ae.entity_id
          JOIN articles a ON a.id = ae.article_id
          JOIN subscriptions s ON s.feed_id = a.feed_id
         WHERE s.user_id = ?
           AND e.type = ?
           AND a.published_at > datetime('now', ?)
         GROUP BY e.id
         ORDER BY c DESC
         LIMIT ?
        """,
        (user.id, type, f"-{days} days", limit),
    ).fetchall()
    return TopEntitiesResponse(
        entities=[
            EntityCount(type=r["type"], name=r["name"],
                        display_name=r["display_name"], count=r["c"])
            for r in rows
        ],
    )


@router.get("/timeseries", response_model=TimeseriesResponse)
def timeseries(
    days: int = Query(default=30, ge=1, le=365),
    bucket: str = Query(default="day", pattern="^(day|hour)$"),
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> TimeseriesResponse:
    fmt = "%Y-%m-%d" if bucket == "day" else "%Y-%m-%d %H:00"
    rows = conn.execute(
        f"""
        SELECT strftime('{fmt}', a.published_at) AS bucket, COUNT(*) AS c
          FROM all_articles a
          JOIN main.subscriptions s ON s.feed_id = a.feed_id
         WHERE s.user_id = ?
           AND a.published_at > datetime('now', ?)
         GROUP BY bucket
         ORDER BY bucket
        """,
        (user.id, f"-{days} days"),
    ).fetchall()
    return TimeseriesResponse(
        buckets=[TimeBucket(bucket=r["bucket"], count=r["c"]) for r in rows],
    )


@router.get("/severity", response_model=SeverityResponse)
def severity_breakdown(
    days: int = Query(default=30, ge=1, le=365),
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> SeverityResponse:
    rows = conn.execute(
        """
        SELECT a.severity_hint AS severity, COUNT(*) AS c
          FROM all_articles a
          JOIN main.subscriptions s ON s.feed_id = a.feed_id
         WHERE s.user_id = ?
           AND a.published_at > datetime('now', ?)
         GROUP BY a.severity_hint
         ORDER BY c DESC
        """,
        (user.id, f"-{days} days"),
    ).fetchall()
    return SeverityResponse(
        breakdown=[SeverityBreakdown(severity=r["severity"], count=r["c"]) for r in rows],
    )
