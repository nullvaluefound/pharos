"""APScheduler-driven feed polling.

Each feed is polled on its own ``poll_interval_sec``. A poll runs the full
ingestion sub-pipeline for that feed: fetch (conditional GET), parse, extract,
dedup, and INSERT new articles with ``enrichment_status='pending'`` so the
lantern picks them up.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import get_settings
from ..db import connect
from .dedup import canonicalize_url, content_simhash, url_hash
from .extractor import extract_text
from .fetcher import fetch, fetch_article_html
from .parser import parse_feed

log = logging.getLogger(__name__)


async def poll_feed(feed_id: int) -> None:
    """Poll a single feed and insert any new articles as pending."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, url, etag, last_modified FROM feeds WHERE id = ?",
            (feed_id,),
        ).fetchone()
    if not row:
        return

    log.info("polling feed %s (%s)", row["id"], row["url"])
    try:
        result = await fetch(row["url"], etag=row["etag"], last_modified=row["last_modified"])
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                "UPDATE feeds SET error_count = error_count + 1, "
                "last_status = ?, last_polled_at = ? WHERE id = ?",
                (f"fetch_error: {exc}", datetime.now(timezone.utc), feed_id),
            )
            conn.commit()
        return

    now = datetime.now(timezone.utc)
    if result.not_modified:
        with connect() as conn:
            conn.execute(
                "UPDATE feeds SET last_polled_at = ?, last_status = '304 Not Modified', "
                "error_count = 0 WHERE id = ?",
                (now, feed_id),
            )
            conn.commit()
        return

    parsed = parse_feed(result.body)

    with connect() as conn:
        conn.execute(
            "UPDATE feeds SET title = COALESCE(title, ?), site_url = COALESCE(site_url, ?), "
            "etag = ?, last_modified = ?, last_polled_at = ?, "
            "last_status = ?, error_count = 0 WHERE id = ?",
            (
                parsed.title,
                parsed.site_url,
                result.etag,
                result.last_modified,
                now,
                f"{result.status_code}",
                feed_id,
            ),
        )
        conn.commit()

    inserted = 0
    for entry in parsed.entries:
        canonical = canonicalize_url(entry.url)
        h = url_hash(canonical)

        with connect() as conn:
            existing = conn.execute(
                "SELECT id FROM articles WHERE url_hash = ? LIMIT 1", (h,)
            ).fetchone()
        if existing:
            continue

        body_html = entry.content_html or entry.summary_html
        if not body_html:
            body_html = await fetch_article_html(canonical)

        text = extract_text(body_html, url=canonical) if body_html else ""
        chash = content_simhash(text) if text else None

        with connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO articles (feed_id, url, url_hash, content_hash, title, "
                    "author, published_at, fetched_at, raw_text, enrichment_status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                    (
                        feed_id,
                        canonical,
                        h,
                        chash,
                        entry.title,
                        entry.author,
                        entry.published_at,
                        now,
                        text,
                    ),
                )
                conn.commit()
                inserted += 1
            except Exception as exc:
                log.warning("insert failed for %s: %s", canonical, exc)

    log.info("feed %s: %d new articles", feed_id, inserted)


async def _schedule_all(scheduler: AsyncIOScheduler) -> None:
    """Add a job per *active* feed at its configured cadence.

    Inactive feeds (``feeds.is_active = 0``) are intentionally skipped so the
    poll loop ignores soft-disabled sources. Any previously-scheduled jobs
    for feeds that have since gone inactive are removed below.
    """
    s = get_settings()
    with connect() as conn:
        feeds = conn.execute(
            "SELECT id, COALESCE(poll_interval_sec, ?) AS interval "
            "FROM feeds WHERE COALESCE(is_active, 1) = 1",
            (s.default_feed_poll_interval_sec,),
        ).fetchall()

    active_ids: set[int] = set()
    for f in feeds:
        active_ids.add(int(f["id"]))
        scheduler.add_job(
            poll_feed,
            "interval",
            seconds=f["interval"],
            args=[f["id"]],
            id=f"feed-{f['id']}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            poll_feed,
            "date",
            args=[f["id"]],
            id=f"feed-{f['id']}-bootstrap",
            replace_existing=True,
        )

    # Drop jobs for feeds that have been deactivated since last loop pass.
    for job in scheduler.get_jobs():
        if not job.id.startswith("feed-"):
            continue
        try:
            fid = int(job.id.split("-")[1])
        except (IndexError, ValueError):
            continue
        if fid not in active_ids:
            log.info("removing scheduler job %s for inactive feed", job.id)
            scheduler.remove_job(job.id)


async def run_forever() -> None:
    logging.basicConfig(level=get_settings().log_level)
    scheduler = AsyncIOScheduler(timezone="UTC")
    await _schedule_all(scheduler)
    scheduler.start()
    log.info("ingestion scheduler started")
    try:
        while True:
            await asyncio.sleep(60)
            await _schedule_all(scheduler)
    finally:
        scheduler.shutdown()
