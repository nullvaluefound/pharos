"""Watch checker: scans newly enriched articles against user watches and
creates in-app notifications when matches are found.

Runs as a periodic job alongside the lantern. Reuses the same query logic
used by ``/search`` so notifications match exactly what the user sees.

Email digests
-------------
After the in-app pass each tick, we also walk the un-emailed
``notifications`` rows whose owning watch has ``notify_email = 1`` and
whose user has a valid ``email`` address. We coalesce them per
(user, watch) into a single digest, ship it via SMTP, and stamp
``email_sent_at`` so we never re-send. SMTP failures leave the rows
un-stamped so the next tick will retry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections import defaultdict
from typing import Any

from ..db import connect
from . import email as mailer

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
    """Check all notify=true OR notify_email=true watches against recent
    unseen enriched articles. Returns the number of new in-app notifications."""
    watches = conn.execute(
        "SELECT id, user_id, name, query_json, notify, notify_email "
        "FROM saved_searches "
        "WHERE notify = 1 OR notify_email = 1",
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
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO notifications "
                        "(user_id, watch_id, article_id, title, body) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            w["user_id"], w["id"], c["id"],
                            f'New match for "{w["name"]}"',
                            (c["title"] or "")[:280],
                        ),
                    )
                    if cur.rowcount:
                        created += 1
            except Exception as e:
                log.warning("watch check failed for %s/%s: %s", w["id"], c["id"], e)
            finally:
                conn.execute(
                    "INSERT OR IGNORE INTO watch_seen_articles (watch_id, article_id) "
                    "VALUES (?, ?)", (w["id"], c["id"]),
                )
    conn.commit()
    return created


# ---------------------------------------------------------------------------
# Email digest pass
# ---------------------------------------------------------------------------
def _send_pending_digests(conn: sqlite3.Connection) -> int:
    """Coalesce un-emailed match notifications into per-watch digests and
    ship them through the configured SMTP relay.

    Returns the number of emails actually sent. Does nothing (returns 0)
    if SMTP isn't configured -- the un-emailed rows simply sit and wait
    for the operator to set SMTP_HOST.
    """
    if not mailer.is_smtp_configured():
        return 0

    pending = conn.execute(
        """
        SELECT n.id              AS notif_id,
               n.user_id          AS user_id,
               n.watch_id         AS watch_id,
               n.article_id       AS article_id,
               u.email            AS email,
               s.name             AS watch_name,
               s.notify_email     AS notify_email,
               a.title            AS title,
               a.overview         AS overview,
               a.severity_hint    AS severity_hint,
               a.published_at     AS published_at,
               f.title            AS feed_title
          FROM notifications n
          JOIN users u           ON u.id = n.user_id
          JOIN saved_searches s  ON s.id = n.watch_id
          LEFT JOIN articles a   ON a.id = n.article_id
          LEFT JOIN feeds f      ON f.id = a.feed_id
         WHERE n.email_sent_at IS NULL
           AND s.notify_email = 1
           AND u.email IS NOT NULL
           AND u.email != ''
         ORDER BY n.watch_id, n.created_at ASC
         LIMIT 2000
        """
    ).fetchall()
    if not pending:
        return 0

    # Bucket by (user_id, watch_id) so each watch produces a single digest.
    buckets: dict[tuple[int, int], dict[str, Any]] = defaultdict(
        lambda: {"email": None, "watch_name": None, "rows": [], "ids": []}
    )
    for p in pending:
        if not mailer.is_valid_email(p["email"]):
            # Stamp it as "sent" so we don't keep re-considering a row
            # that can never deliver. The user can fix their email and
            # subsequent matches will go out.
            conn.execute(
                "UPDATE notifications SET email_sent_at = CURRENT_TIMESTAMP "
                "WHERE id = ?", (p["notif_id"],),
            )
            continue
        if not p["title"]:
            # The article was deleted / archived between match-time and
            # send-time. Stamp & skip so we don't email a broken link.
            conn.execute(
                "UPDATE notifications SET email_sent_at = CURRENT_TIMESTAMP "
                "WHERE id = ?", (p["notif_id"],),
            )
            continue
        key = (p["user_id"], p["watch_id"])
        b = buckets[key]
        b["email"] = p["email"]
        b["watch_name"] = p["watch_name"]
        b["rows"].append(
            mailer.DigestArticle(
                article_id=p["article_id"],
                title=p["title"],
                feed_title=p["feed_title"],
                published_at=p["published_at"],
                overview=p["overview"],
                severity_hint=p["severity_hint"],
            )
        )
        b["ids"].append(p["notif_id"])
    conn.commit()

    sent = 0
    for (user_id, watch_id), b in buckets.items():
        if not b["rows"]:
            continue
        try:
            subject, text, html = mailer.render_digest(
                watch_name=b["watch_name"] or "Watch",
                articles=b["rows"],
            )
            mailer.send_email(to=b["email"], subject=subject, text=text, html=html)
        except Exception as e:
            # Leave email_sent_at NULL so the next tick retries. Log loudly
            # so the operator can see why deliveries are stuck.
            log.warning(
                "digest send failed for user=%s watch=%s (%d rows): %s",
                user_id, watch_id, len(b["rows"]), e,
            )
            continue

        # Stamp every row in the digest in one statement.
        placeholders = ",".join("?" * len(b["ids"]))
        conn.execute(
            f"UPDATE notifications SET email_sent_at = CURRENT_TIMESTAMP "
            f"WHERE id IN ({placeholders})",
            b["ids"],
        )
        conn.commit()
        sent += 1
    return sent


async def run_forever(interval_sec: int = 60) -> None:
    """Periodic watch-check + email-digest + scheduled-report loop."""
    # Imported here (rather than at module-level) so a circular-import
    # chain via pharos.reports doesn't trip the notifier package boot.
    from ..reports import run_due_schedules

    log.info("notifier started (interval=%ss)", interval_sec)
    while True:
        try:
            with connect() as conn:
                _check_once(conn)
                _send_pending_digests(conn)
                # Recurring reports. ``run_due_schedules`` is async because
                # it talks to OpenAI; it's a no-op when nothing is due.
                await run_due_schedules(conn)
        except Exception as e:
            log.warning("notifier tick failed: %s", e)
        await asyncio.sleep(interval_sec)
