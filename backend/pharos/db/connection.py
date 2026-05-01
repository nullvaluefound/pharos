"""SQLite connection helpers.

Pharos uses two SQLite files:
  - hot.db   : recent articles + all operational state
  - cold.db  : archived articles ("the archeion")

We open one connection against hot.db and ATTACH cold.db as schema "cold",
allowing cross-DB UNION ALL reads through a temp view ``all_articles``.

Migrations
----------
The base schema lives in ``schema_hot.sql`` and uses ``CREATE TABLE IF NOT
EXISTS``, so it's idempotent and safe to run on every boot. Forward-only
migrations live in ``migrations/NNNN_*.sql`` and are applied in numeric
order; the highest applied version is recorded in the ``schema_version``
table. SQLite has no ``ADD COLUMN IF NOT EXISTS``, so the runner is what
keeps these idempotent.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Iterator

from ..config import get_settings

log = logging.getLogger(__name__)


def _read_sql(filename: str) -> str:
    return resources.files("pharos.db").joinpath(filename).read_text(encoding="utf-8")


_MIGRATION_PATTERN = re.compile(r"^(\d+)_.+\.sql$")


def _list_migrations() -> list[tuple[int, str]]:
    """Return [(version, filename)] for every shipped migration, ascending."""
    out: list[tuple[int, str]] = []
    try:
        for entry in resources.files("pharos.db").joinpath("migrations").iterdir():
            name = entry.name
            m = _MIGRATION_PATTERN.match(name)
            if m:
                out.append((int(m.group(1)), name))
    except (FileNotFoundError, ModuleNotFoundError):
        return []
    out.sort()
    return out


def _current_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["v"] or 0) if row else 0


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Run every migration whose version > current schema_version."""
    current = _current_schema_version(conn)
    for version, fname in _list_migrations():
        if version <= current:
            continue
        log.info("applying migration %s (v%s)", fname, version)
        sql = (
            resources.files("pharos.db")
            .joinpath("migrations")
            .joinpath(fname)
            .read_text(encoding="utf-8")
        )
        conn.executescript(sql)
        conn.commit()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA busy_timeout = 5000;")


def init_databases() -> None:
    """Create hot.db and cold.db with schema if they do not exist."""
    s = get_settings()
    s.pharos_db_dir.mkdir(parents=True, exist_ok=True)

    hot = sqlite3.connect(s.hot_db_path)
    hot.row_factory = sqlite3.Row
    try:
        _apply_pragmas(hot)
        hot.executescript(_read_sql("schema_hot.sql"))
        hot.commit()
        _apply_migrations(hot)
    finally:
        hot.close()

    cold = sqlite3.connect(s.cold_db_path)
    try:
        _apply_pragmas(cold)
        cold.executescript(_read_sql("schema_cold.sql"))
        cold.commit()
    finally:
        cold.close()


def _create_unified_view(conn: sqlite3.Connection) -> None:
    """Create a TEMP view that unions hot + cold articles for read paths."""
    conn.executescript(
        """
        DROP VIEW IF EXISTS all_articles;
        CREATE TEMP VIEW all_articles AS
            SELECT id, feed_id, url, url_hash, content_hash, title, author,
                   published_at, fetched_at, enriched_json, overview, language,
                   severity_hint, enrichment_status, fingerprint,
                   story_cluster_id, cluster_similarity, 'hot' AS tier
              FROM main.articles
            UNION ALL
            SELECT id, feed_id, url, url_hash, content_hash, title, author,
                   published_at, fetched_at, enriched_json, overview, language,
                   severity_hint, enrichment_status, fingerprint,
                   story_cluster_id, cluster_similarity, 'cold' AS tier
              FROM cold.articles;
        """
    )


@contextmanager
def connect(*, attach_cold: bool = True) -> Iterator[sqlite3.Connection]:
    """Open a connection to hot.db (with cold.db attached by default)."""
    s = get_settings()
    if not Path(s.hot_db_path).exists():
        init_databases()
    conn = sqlite3.connect(
        s.hot_db_path,
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,  # autocommit; transactions managed explicitly
        check_same_thread=False,  # FastAPI sync handlers run in a threadpool
    )
    conn.row_factory = sqlite3.Row
    try:
        _apply_pragmas(conn)
        if attach_cold:
            conn.execute("ATTACH DATABASE ? AS cold;", (str(s.cold_db_path),))
            _create_unified_view(conn)
        yield conn
    finally:
        conn.close()
