"""Watch checker: scans newly enriched articles against user watches and
creates in-app notifications when matches are found.

Runs as a periodic job alongside the lantern. Reuses the same query logic
used by ``/search`` so notifications match exactly what the user sees.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Any

from ..db import connect

log = logging.getLogger(__name__)


def _entity_ids(conn: sqlite3.Connection, type_: str, names: list[str]) -> list[int]:
    if not names:
        return []
    placeholders = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT id FROM main.entities WHERE type = ? AND canonical_name IN ({placeholders})",
        (type_, *[n.lower() for n in names]),
    ).fetchall()
    return [r["id"] for r in rows]


def _matches_watch(conn: sqlite3.Connection, query: dict[str, Any], user_id: int,
                   article_id: int) -> bool:
    """Return True if the given article matches the watch query."""
    where = ["a.id = ?", "s.user_id = ?"]
    params: list = [article_id, user_id]

    any_of = query.get("any_of", {})
    all_of = query.get("all_of", {})
    none_of = query.get("none_of", {})
    has_types = query.get("has_entity_types", []) or []
    text = query.get("text")

    any_ids: list[int] = []
    for t, names in any_of.items():
        any_ids.extend(_entity_ids(conn, t, names))
    if any_of and not any_ids:
        return False
    if any_ids:
        ph = ",".join("?" * len(any_ids))
        where.append(
            f"a.id IN (SELECT article_id FROM main.article_entities "
            f"WHERE entity_id IN ({ph}))"
        )
        params.extend(any_ids)

    for t, names in all_of.items():
        for eid in _entity_ids(conn, t, names):
            where.append(
                "a.id IN (SELECT article_id FROM main.article_entities WHERE entity_id = ?)"
            )
            params.append(eid)

    for t, names in none_of.items():
        ids = _entity_ids(conn, t, names)
        if not ids:
            continue
        ph = ",".join("?" * len(ids))
        where.append(
            f"a.id NOT IN (SELECT article_id FROM main.article_entities "
            f"WHERE entity_id IN ({ph}))"
        )
        params.extend(ids)

    for etype in has_types:
        where.append(
            "a.id IN (SELECT ae.article_id FROM main.article_entities ae "
            "JOIN main.entities e ON e.id = ae.entity_id WHERE e.type = ?)"
        )
        params.append(etype)

    if text:
        where.append(
            "a.id IN (SELECT rowid FROM main.articles_fts WHERE articles_fts MATCH ?)"
        )
        params.append(text)

    sql = (
        "SELECT 1 FROM main.articles a "
        "JOIN main.subscriptions s ON s.feed_id = a.feed_id "
        f"WHERE {' AND '.join(where)} LIMIT 1"
    )
    return conn.execute(sql, params).fetchone() is not None


def _check_once(conn: sqlite3.Connection) -> int:
    """Check all notify=true watches against recent unseen enriched articles."""
    watches = conn.execute(
        "SELECT id, user_id, name, query_json FROM saved_searches WHERE notify = 1",
    ).fetchall()
    if not watches:
        return 0

    created = 0
    for w in watches:
        try:
            query = json.loads(w["query_json"]) if w["query_json"] else {}
        except json.JSONDecodeError:
            continue
        # Look at recently enriched articles the user can see
        candidates = conn.execute(
            """
            SELECT a.id, a.title
              FROM articles a
              JOIN subscriptions s ON s.feed_id = a.feed_id
             WHERE s.user_id = ?
               AND a.enrichment_status = 'enriched'
               AND a.id NOT IN (
                   SELECT article_id FROM watch_seen_articles WHERE watch_id = ?
               )
               AND a.published_at > datetime('now', '-7 days')
             ORDER BY a.published_at DESC
             LIMIT 200
            """,
            (w["user_id"], w["id"]),
        ).fetchall()
        for c in candidates:
            try:
                if _matches_watch(conn, query, w["user_id"], c["id"]):
                    conn.execute(
                        "INSERT OR IGNORE INTO notifications "
                        "(user_id, watch_id, article_id, title, body) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            w["user_id"], w["id"], c["id"],
                            f'New match for "{w["name"]}"',
                            (c["title"] or "")[:280],
                        ),
                    )
                    created += conn.total_changes  # not exact but indicative
            except Exception as e:
                log.warning("watch check failed for %s/%s: %s", w["id"], c["id"], e)
            finally:
                conn.execute(
                    "INSERT OR IGNORE INTO watch_seen_articles (watch_id, article_id) "
                    "VALUES (?, ?)", (w["id"], c["id"]),
                )
    conn.commit()
    return created


async def run_forever(interval_sec: int = 60) -> None:
    """Periodic watch-check loop."""
    log.info("notifier started (interval=%ss)", interval_sec)
    while True:
        try:
            with connect() as conn:
                _check_once(conn)
        except Exception as e:
            log.warning("notifier tick failed: %s", e)
        await asyncio.sleep(interval_sec)
