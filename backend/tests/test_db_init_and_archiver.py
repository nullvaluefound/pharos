"""Smoke test: init the DB, insert an enriched article + tokens, archive it."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def test_init_then_archive_roundtrip(tmp_db_dir):
    from pharos.archiver.job import archive_once
    from pharos.db import connect, init_databases

    init_databases()

    old_pub = datetime.now(timezone.utc) - timedelta(days=120)
    with connect(attach_cold=False) as conn:
        cur = conn.execute(
            "INSERT INTO feeds (url, poll_interval_sec) VALUES (?, ?)",
            ("https://example.com/feed", 900),
        )
        feed_id = cur.lastrowid

        cur = conn.execute(
            "INSERT INTO articles (feed_id, url, url_hash, title, fetched_at, "
            "published_at, enriched_json, overview, enrichment_status, fingerprint) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'enriched', ?)",
            (
                feed_id,
                "https://example.com/a",
                "h" * 64,
                "Old article",
                old_pub,
                old_pub,
                json.dumps({"overview": "x"}),
                "x",
                json.dumps(["w:foo", "thr:apt29"]),
            ),
        )
        aid = cur.lastrowid
        conn.executemany(
            "INSERT INTO article_tokens(token, article_id) VALUES (?, ?)",
            [("w:foo", aid), ("thr:apt29", aid)],
        )
        conn.commit()

    moved = archive_once()
    assert moved == 1

    with connect() as conn:
        hot = conn.execute("SELECT COUNT(*) AS c FROM main.articles").fetchone()
        cold = conn.execute("SELECT COUNT(*) AS c FROM cold.articles").fetchone()
        unified = conn.execute(
            "SELECT COUNT(*) AS c FROM all_articles"
        ).fetchone()
    assert hot["c"] == 0
    assert cold["c"] == 1
    assert unified["c"] == 1
