"""Soft-deactivate any feed in hot.db whose URL is not in the curated catalog.

The curated catalog lives at ``backend/pharos/data/default_feeds.yaml``. This
script:

  1. Loads every URL listed in the catalog (across all categories).
  2. Loads every URL from the feeds table.
  3. Sets ``is_active = 1`` on feeds whose URL appears in the catalog.
  4. Sets ``is_active = 0`` on every other feed.

No rows are deleted. All previously-enriched articles remain queryable; the
only effect is that the scheduler stops polling deactivated feeds.

Usage:
    # Inside the docker container (DB at /data/hot.db):
    python /opt/pharos/scripts/apply_feed_allowlist.py

    # Or with a custom DB path:
    python apply_feed_allowlist.py --db /path/to/hot.db --dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_catalog_urls(yaml_path: Path | None = None) -> set[str]:
    """Parse default_feeds.yaml and return every feed URL in the catalog."""
    if yaml_path is None:
        yaml_path = (
            _project_root()
            / "backend" / "pharos" / "data" / "default_feeds.yaml"
        )
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    urls: set[str] = set()
    for cat in raw.get("categories", []):
        for feed in cat.get("feeds", []) or []:
            url = (feed.get("url") or "").strip()
            if url:
                urls.add(url)
    return urls


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="/data/hot.db", help="Path to hot.db")
    p.add_argument("--catalog", default=None, help="Path to default_feeds.yaml")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would change without writing.")
    p.add_argument("--reactivate-allowlist", action="store_true", default=True,
                   help="Also flip is_active=1 on catalog feeds (default true).")
    args = p.parse_args()

    catalog_path = Path(args.catalog) if args.catalog else None
    allow = load_catalog_urls(catalog_path)
    print(f"Catalog: {len(allow)} curated URLs")

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    # Column may not exist yet on a freshly-pulled DB -- run migrations first.
    cols = {r[1] for r in db.execute("PRAGMA table_info(feeds)")}
    if "is_active" not in cols:
        print("ERROR: feeds.is_active column missing. Run the backend once "
              "to apply migration 0002 first.", file=sys.stderr)
        return 2

    rows = db.execute("SELECT id, url, is_active FROM feeds").fetchall()
    total = len(rows)
    in_catalog = [r for r in rows if r["url"] in allow]
    not_in = [r for r in rows if r["url"] not in allow]

    will_deactivate = [r for r in not_in if r["is_active"]]
    will_activate = [r for r in in_catalog if not r["is_active"]] if args.reactivate_allowlist else []

    print(f"Total feeds in DB:           {total}")
    print(f"  on the curated allowlist:  {len(in_catalog)}")
    print(f"  NOT on the allowlist:      {len(not_in)}")
    print()
    print(f"  -> will set is_active=0 on {len(will_deactivate)} feed(s)")
    if args.reactivate_allowlist:
        print(f"  -> will set is_active=1 on {len(will_activate)} feed(s) "
              "(re-enabling any catalog feeds previously deactivated)")

    # Show a sample so the operator can sanity-check.
    if will_deactivate:
        print("\nSample of feeds that will be deactivated:")
        for r in will_deactivate[:8]:
            print(f"   id={r['id']:>4}  {r['url']}")
        if len(will_deactivate) > 8:
            print(f"   ... and {len(will_deactivate) - 8} more")

    if args.dry_run:
        print("\n-- dry run, no changes written --")
        return 0

    if will_deactivate:
        db.executemany(
            "UPDATE feeds SET is_active = 0 WHERE id = ?",
            [(r["id"],) for r in will_deactivate],
        )
    if will_activate:
        db.executemany(
            "UPDATE feeds SET is_active = 1 WHERE id = ?",
            [(r["id"],) for r in will_activate],
        )
    db.commit()

    after = db.execute(
        "SELECT SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active, "
        "       SUM(CASE WHEN is_active=0 THEN 1 ELSE 0 END) AS inactive "
        "FROM feeds"
    ).fetchone()
    print(f"\nDone. Active: {after['active']}  Inactive: {after['inactive']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
