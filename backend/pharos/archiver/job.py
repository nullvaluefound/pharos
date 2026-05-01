"""Hot -> cold archiver.

Articles older than ``ARCHIVE_AFTER_DAYS`` (and already enriched) are copied
into ``cold.db`` and removed from ``hot.db``. Raw HTML/text is dropped at this
point; the structured ``enriched_json`` is what we keep long-term.

USER DATA POLICY -- IMPORTANT
-----------------------------
The archiver only ever touches *article* state. It never moves, deletes, or
mutates any of the per-user tables, which always live in hot.db:

  - users
  - subscriptions
  - user_folders
  - user_article_state    (read / saved / star)
  - saved_searches        (watches)
  - bookmarks
  - notifications
  - reports

These references survive the move because article IDs are preserved
across the hot -> cold copy. ``user_article_state.article_id`` continues
to point at the same logical article -- the unified ``all_articles``
view (``hot UNION ALL cold``) makes this transparent to the API.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import get_settings
from ..db import connect

log = logging.getLogger(__name__)


def archive_once(*, batch_size: int = 500) -> int:
    """Run one pass of the archiver. Returns number of articles archived."""
    s = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=s.archive_after_days)
    total = 0

    with connect() as conn:
        while True:
            rows = conn.execute(
                "SELECT id FROM main.articles "
                "WHERE enrichment_status IN ('enriched','failed') "
                "  AND COALESCE(published_at, fetched_at) < ? "
                "ORDER BY COALESCE(published_at, fetched_at) ASC LIMIT ?",
                (cutoff, batch_size),
            ).fetchall()
            if not rows:
                break

            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))

            try:
                conn.execute("BEGIN IMMEDIATE")

                conn.execute(
                    f"INSERT OR REPLACE INTO cold.articles "
                    f"(id, feed_id, url, url_hash, content_hash, title, author, "
                    f" published_at, fetched_at, enriched_json, overview, language, "
                    f" severity_hint, enrichment_status, fingerprint, "
                    f" story_cluster_id, cluster_similarity, archived_at) "
                    f"SELECT id, feed_id, url, url_hash, content_hash, title, author, "
                    f"       published_at, fetched_at, enriched_json, overview, language, "
                    f"       severity_hint, 'archived', fingerprint, "
                    f"       story_cluster_id, cluster_similarity, ? "
                    f"FROM main.articles WHERE id IN ({placeholders})",
                    (datetime.now(timezone.utc), *ids),
                )

                conn.execute(
                    f"INSERT OR IGNORE INTO cold.article_entities "
                    f"(article_id, entity_id, confidence, role) "
                    f"SELECT article_id, entity_id, confidence, role "
                    f"FROM main.article_entities "
                    f"WHERE article_id IN ({placeholders})",
                    ids,
                )

                conn.execute(
                    f"INSERT OR IGNORE INTO cold.article_tokens (token, article_id) "
                    f"SELECT token, article_id FROM main.article_tokens "
                    f"WHERE article_id IN ({placeholders})",
                    ids,
                )

                cluster_ids = conn.execute(
                    f"SELECT DISTINCT story_cluster_id FROM main.articles "
                    f"WHERE id IN ({placeholders}) AND story_cluster_id IS NOT NULL",
                    ids,
                ).fetchall()
                for cr in cluster_ids:
                    conn.execute(
                        "INSERT OR REPLACE INTO cold.story_clusters "
                        "(id, representative_article_id, first_seen_at, last_seen_at, member_count) "
                        "SELECT id, representative_article_id, first_seen_at, last_seen_at, "
                        "       member_count FROM main.story_clusters WHERE id = ?",
                        (cr["story_cluster_id"],),
                    )

                blob_paths = conn.execute(
                    f"SELECT raw_html_path FROM main.articles "
                    f"WHERE id IN ({placeholders}) AND raw_html_path IS NOT NULL",
                    ids,
                ).fetchall()

                conn.execute(
                    f"DELETE FROM main.article_tokens WHERE article_id IN ({placeholders})",
                    ids,
                )
                conn.execute(
                    f"DELETE FROM main.article_entities WHERE article_id IN ({placeholders})",
                    ids,
                )
                conn.execute(
                    f"DELETE FROM main.articles_fts WHERE rowid IN ({placeholders})",
                    ids,
                )
                conn.execute(
                    f"DELETE FROM main.articles WHERE id IN ({placeholders})",
                    ids,
                )

                conn.execute("COMMIT")

                for br in blob_paths:
                    p = br["raw_html_path"]
                    if p:
                        try:
                            Path(p).unlink(missing_ok=True)
                        except OSError as exc:
                            log.warning("could not delete blob %s: %s", p, exc)

                total += len(ids)
                log.info("archived %d articles (running total %d)", len(ids), total)
            except Exception:
                conn.execute("ROLLBACK")
                raise

    log.info("archive_once complete: %d articles moved", total)
    return total
