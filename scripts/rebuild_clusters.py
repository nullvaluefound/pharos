"""Rebuild story clusters in the hot DB using the current Constellations logic.

Use this after changing fingerprint / clustering rules (e.g. the move to
anchor-gated weighted Jaccard) to re-bin existing articles. Safe to re-run.

What it does:
1. Wipes legacy ``ttp:*`` and ``mta:*`` rows from ``article_tokens``
   (we no longer cluster on MITRE Techniques or Tactics).
2. Resets ``story_cluster_id`` and ``cluster_similarity`` on every hot
   article and truncates ``story_clusters``.
3. Walks articles in chronological order and re-runs
   :func:`pharos.lantern.constellations.assign_constellation` on each
   article using its persisted token set. The clustering window means
   each article only looks back ``cluster_window_days`` -- so the order
   of processing matches what the live worker sees.

Run inside the API/worker container:
    docker exec -it pharos-pharos-1 \
        python -m scripts.rebuild_clusters
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Make ``scripts.*`` importable when run as a module from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pharos.db.connection import connect  # noqa: E402
from pharos.lantern.constellations import assign_constellation  # noqa: E402


def main() -> int:
    with connect(attach_cold=False) as conn:
        return _rebuild(conn)


def _rebuild(conn) -> int:
    # 1. Drop legacy MITRE-tactic / -technique tokens.
    cur = conn.execute(
        "DELETE FROM article_tokens "
        "WHERE token LIKE 'ttp:%' OR token LIKE 'mta:%'"
    )
    legacy_deleted = cur.rowcount
    conn.commit()
    print(f"[1/4] Removed {legacy_deleted} legacy ttp:/mta: token rows.")

    # 2. Reset cluster assignments + clear the story_clusters table.
    conn.execute(
        "UPDATE articles "
        "   SET story_cluster_id = NULL, "
        "       cluster_similarity = NULL "
        " WHERE story_cluster_id IS NOT NULL"
    )
    conn.execute("DELETE FROM story_clusters")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'story_clusters'")
    conn.commit()
    print("[2/4] Cleared story_clusters and reset cluster_id on all articles.")

    # 3. Pull every article that has at least one token, oldest first.
    rows = conn.execute(
        """
        SELECT a.id
          FROM articles a
         WHERE a.published_at IS NOT NULL
           AND EXISTS (
             SELECT 1 FROM article_tokens at WHERE at.article_id = a.id
           )
         ORDER BY a.published_at ASC
        """
    ).fetchall()
    total = len(rows)
    print(f"[3/4] Re-clustering {total} articles in chronological order...")

    t0 = time.time()
    new_clusters = 0
    joined = 0
    for i, r in enumerate(rows, start=1):
        aid = int(r["id"])
        tok_rows = conn.execute(
            "SELECT token FROM article_tokens WHERE article_id = ?", (aid,)
        ).fetchall()
        tokens = sorted({t["token"] for t in tok_rows})
        if not tokens:
            continue
        cluster_id, sim = assign_constellation(
            conn, article_id=aid, tokens=tokens
        )
        if sim == 1.0:
            new_clusters += 1
        else:
            joined += 1
        if i % 250 == 0:
            elapsed = time.time() - t0
            rate = i / max(elapsed, 1e-6)
            eta = (total - i) / max(rate, 1e-6)
            print(
                f"  {i}/{total} processed  "
                f"({new_clusters} new, {joined} joined)  "
                f"~{rate:.1f}/s  eta {eta:.0f}s"
            )
        if i % 1000 == 0:
            conn.commit()

    conn.commit()
    elapsed = time.time() - t0
    print(
        f"[4/4] Done in {elapsed:.1f}s. "
        f"{new_clusters} new clusters, {joined} articles joined an existing cluster."
    )

    summary = conn.execute(
        "SELECT COUNT(*) AS clusters, "
        "       SUM(CASE WHEN member_count > 1 THEN 1 ELSE 0 END) AS multi_member, "
        "       MAX(member_count) AS biggest "
        "  FROM story_clusters"
    ).fetchone()
    print(
        f"      story_clusters: total={summary['clusters']}  "
        f"multi-member={summary['multi_member']}  "
        f"largest={summary['biggest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
