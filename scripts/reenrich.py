"""Mark articles for re-enrichment by the lantern worker.

Selectors (composable, repeatable):

  --failed
        Reset every article whose enrichment_status = 'failed' to 'pending'.

  --actor-without-mitre
        Reset every article that has at least one threat_actor extracted
        but no mitre_group_id on any of them. Useful after we ship the
        Malpedia canonicalization step so the worker can fill in IDs.

  --empty-entities
        Reset every enriched article whose entities object has every list
        empty. WARNING: many of these are legitimately metadata-free
        articles (essays, opinion pieces) and respending tokens on them
        is wasteful. Prefer the more targeted selectors.

  --stuck-in-progress
        Reset 'in_progress' articles back to 'pending'. Useful if a worker
        crashed and left rows orphaned.

  --ids 1234,5678
        Reset just these specific article IDs.

  --dry-run
        Show what would be reset, don't change anything.

  --limit N
        Cap the number of resets (sanity guard).

This script reads the live hot.db. It is intended to be run inside the
pharos backend container or against a copy of hot.db. Always take a
snapshot first via `python scripts/deploy_do.py --no-source --no-build`
or by tarballing the docker volume.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


def _build_selectors(args: argparse.Namespace) -> list[tuple[str, str, tuple]]:
    """Return a list of (label, where_clause, params) tuples to OR together."""
    sel: list[tuple[str, str, tuple]] = []
    if args.failed:
        sel.append(("failed", "enrichment_status = 'failed'", ()))
    if args.stuck_in_progress:
        sel.append(("stuck", "enrichment_status = 'in_progress'", ()))
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
        if ids:
            placeholders = ",".join("?" * len(ids))
            sel.append((f"ids({len(ids)})", f"id IN ({placeholders})", tuple(ids)))
    return sel


def main() -> int:
    p = argparse.ArgumentParser(description="Mark articles for re-enrichment.")
    p.add_argument("--db", default=os.environ.get("PHAROS_HOT_DB", "/data/hot.db"),
                   help="Path to hot.db (default: %(default)s)")
    p.add_argument("--failed", action="store_true",
                   help="Reset enrichment_status = 'failed' rows.")
    p.add_argument("--actor-without-mitre", action="store_true",
                   help="Reset enriched rows where threat_actors[] populated "
                        "but no actor has mitre_group_id.")
    p.add_argument("--empty-entities", action="store_true",
                   help="Reset enriched rows where every entity list is empty.")
    p.add_argument("--stuck-in-progress", action="store_true",
                   help="Reset rows stuck in 'in_progress' state.")
    p.add_argument("--ids", default="",
                   help="Comma-separated article IDs to reset.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print counts only.")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap the number of rows updated.")
    args = p.parse_args()

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"hot.db not found at {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    to_reset: set[int] = set()

    selectors = _build_selectors(args)
    for label, where, params in selectors:
        rows = conn.execute(
            f"SELECT id FROM articles WHERE {where}",
            params,
        ).fetchall()
        ids = {r["id"] for r in rows}
        print(f"  selector {label!r:>32}: {len(ids)} candidates")
        to_reset |= ids

    # JSON-introspection selectors below scan enriched_json so we evaluate
    # them in Python rather than SQL.
    if args.actor_without_mitre or args.empty_entities:
        rows = conn.execute(
            "SELECT id, enriched_json FROM articles "
            "WHERE enrichment_status = 'enriched' AND enriched_json IS NOT NULL"
        ).fetchall()
        actor_no_mitre = 0
        empty_entities = 0
        for r in rows:
            try:
                e = json.loads(r["enriched_json"])
            except Exception:
                continue
            entities = e.get("entities") or {}

            if args.actor_without_mitre:
                actors = entities.get("threat_actors") or []
                if actors and not any(
                    isinstance(a, dict) and a.get("mitre_group_id")
                    for a in actors
                ) and not (entities.get("mitre_groups") or []):
                    to_reset.add(r["id"])
                    actor_no_mitre += 1

            if args.empty_entities:
                has_any = False
                for k, v in entities.items():
                    if isinstance(v, list) and v:
                        has_any = True
                        break
                    if isinstance(v, dict):
                        for sub_v in v.values():
                            if isinstance(sub_v, list) and sub_v:
                                has_any = True
                                break
                        if has_any:
                            break
                if not has_any:
                    to_reset.add(r["id"])
                    empty_entities += 1

        if args.actor_without_mitre:
            print(f"  selector {'actor_without_mitre':>32}: {actor_no_mitre} candidates")
        if args.empty_entities:
            print(f"  selector {'empty_entities':>32}: {empty_entities} candidates")

    if not to_reset:
        print("Nothing to reset.")
        return 0

    ids = sorted(to_reset)
    if args.limit and len(ids) > args.limit:
        print(f"Limiting from {len(ids)} -> {args.limit} (use --limit to override)")
        ids = ids[: args.limit]

    print()
    print(f"Total unique articles to reset: {len(ids)}")
    if args.dry_run:
        print("(dry run -- no changes made)")
        return 0

    chunk = 500
    total = 0
    for i in range(0, len(ids), chunk):
        batch = ids[i : i + chunk]
        placeholders = ",".join("?" * len(batch))
        cur = conn.execute(
            f"UPDATE articles SET enrichment_status = 'pending', "
            f"enrichment_error = NULL WHERE id IN ({placeholders})",
            batch,
        )
        total += cur.rowcount
    conn.commit()
    conn.close()
    print(f"  reset {total} articles to 'pending'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
