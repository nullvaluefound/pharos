"""Admin endpoints: pipeline status, reprocess, manual archive trigger."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...archiver.job import archive_once
from ...feeds import load_catalog, seed_user
from ..deps import CurrentUser, get_db, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


class PipelineStatus(BaseModel):
    counts_by_status: dict[str, int]
    feeds: int
    subscriptions: int
    users: int
    cold_articles: int


@router.get("/pipeline", response_model=PipelineStatus)
def pipeline_status(_: CurrentUser = Depends(require_admin),
                    conn: sqlite3.Connection = Depends(get_db)) -> PipelineStatus:
    rows = conn.execute(
        "SELECT enrichment_status, COUNT(*) AS c FROM main.articles GROUP BY 1"
    ).fetchall()
    counts = {r["enrichment_status"]: int(r["c"]) for r in rows}
    feeds = int(conn.execute("SELECT COUNT(*) AS c FROM main.feeds").fetchone()["c"])
    subs = int(conn.execute("SELECT COUNT(*) AS c FROM main.subscriptions").fetchone()["c"])
    users = int(conn.execute("SELECT COUNT(*) AS c FROM main.users").fetchone()["c"])
    cold = int(conn.execute("SELECT COUNT(*) AS c FROM cold.articles").fetchone()["c"])
    return PipelineStatus(
        counts_by_status=counts, feeds=feeds, subscriptions=subs,
        users=users, cold_articles=cold,
    )


class ReprocessIn(BaseModel):
    article_ids: list[int] | None = None
    failed_only: bool = False


@router.post("/reprocess")
def reprocess(data: ReprocessIn,
              _: CurrentUser = Depends(require_admin),
              conn: sqlite3.Connection = Depends(get_db)) -> dict:
    if data.article_ids:
        placeholders = ",".join("?" * len(data.article_ids))
        cur = conn.execute(
            f"UPDATE main.articles SET enrichment_status = 'pending', "
            f"enrichment_error = NULL WHERE id IN ({placeholders})",
            data.article_ids,
        )
    elif data.failed_only:
        cur = conn.execute(
            "UPDATE main.articles SET enrichment_status = 'pending', "
            "enrichment_error = NULL WHERE enrichment_status = 'failed'"
        )
    else:
        cur = conn.execute(
            "UPDATE main.articles SET enrichment_status = 'pending', "
            "enrichment_error = NULL WHERE enrichment_status IN ('failed','in_progress')"
        )
    conn.commit()
    return {"reset": cur.rowcount}


@router.post("/archive")
def trigger_archive(_: CurrentUser = Depends(require_admin)) -> dict:
    moved = archive_once()
    return {"archived": moved}


# ---------------------------------------------------------------------------
# Curated feed catalog
# ---------------------------------------------------------------------------
class CatalogFeed(BaseModel):
    title: str | None
    url: str
    folder: str | None
    tags: list[str]


class CatalogCategory(BaseModel):
    id: str
    name: str
    folder: str
    description: str
    enabled_by_default: bool
    feeds: list[CatalogFeed]


class CatalogPreset(BaseModel):
    id: str
    name: str
    description: str
    categories: list[str]


class CatalogResponse(BaseModel):
    categories: list[CatalogCategory]
    presets: list[CatalogPreset]


@router.get("/feed-catalog", response_model=CatalogResponse)
def feed_catalog(_: CurrentUser = Depends(require_admin)) -> CatalogResponse:
    """Return the bundled curated feed catalog (categories + presets)."""
    cat = load_catalog()
    return CatalogResponse(
        categories=[
            CatalogCategory(
                id=c.id, name=c.name, folder=c.folder, description=c.description,
                enabled_by_default=c.enabled_by_default,
                feeds=[
                    CatalogFeed(title=f.title, url=f.url,
                                folder=f.folder, tags=f.tags)
                    for f in c.feeds
                ],
            )
            for c in cat.categories
        ],
        presets=[
            CatalogPreset(id=p.id, name=p.name, description=p.description,
                          categories=p.categories)
            for p in cat.presets
        ],
    )


class SeedFeedsIn(BaseModel):
    username: str
    category_ids: list[str] | None = None
    preset_id: str | None = None


@router.post("/seed-feeds")
def seed_feeds(data: SeedFeedsIn,
               _: CurrentUser = Depends(require_admin)) -> dict:
    """Subscribe a user to the bundled curated feeds.

    Either ``category_ids`` OR ``preset_id`` may be provided; if neither is
    set, every category with ``enabled_by_default=true`` is applied.
    """
    if data.category_ids and data.preset_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "category_ids and preset_id are mutually exclusive",
        )
    try:
        result = seed_user(
            username=data.username,
            category_ids=data.category_ids,
            preset_id=data.preset_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {
        "added_subscriptions": result.added_subscriptions,
        "skipped_existing": result.skipped_existing,
        "new_feeds": result.new_feeds,
        "by_category": result.by_category,
    }
