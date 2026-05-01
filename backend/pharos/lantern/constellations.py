"""Story-cluster ("constellation") assignment using weighted Jaccard.

Algorithm:
1. After enrichment, the article has a set of namespaced tokens (fingerprint).
2. We use the ``article_tokens`` inverted index in SQLite to find candidate
   articles published within ``CLUSTER_WINDOW_DAYS`` that share at least
   ``CLUSTER_MIN_SHARED`` tokens with the new article.
3. For each candidate we compute weighted Jaccard similarity. High-signal
   namespaces (CVE, TTP, threat actor, malware) are weighted more heavily.
4. If the best similarity meets ``CLUSTER_SIM_THRESHOLD`` we attach the new
   article to that cluster; otherwise we create a new constellation.

This is fully deterministic and explainable -- the API exposes the matched
tokens through ``/articles/{id}/related``.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from ..config import get_settings

# Token-namespace weights. Keep in sync with prefixes in fingerprint.py.
# Canonical MITRE identifiers carry the strongest signal because they are
# unambiguous globally; CVEs are similarly precise. Free-text actor/malware
# names get weighted lower than their MITRE IDs to favor canonical matches.
NAMESPACE_WEIGHTS: dict[str, int] = {
    "cve":  5,   # CVE identifier
    "mtg":  5,   # MITRE Group ID (G####)
    "mts":  5,   # MITRE Software ID (S####)
    "ttp":  4,   # MITRE Technique / Sub-technique
    "mta":  3,   # MITRE Tactic
    "thr":  4,   # threat actor canonical name
    "mal":  3,   # malware canonical name
    "tool": 2,
    "pro":  2,
    "com":  2,
    "ven":  2,
    "sec":  1,
    "geo":  1,
    "top":  1,
    "w":    1,
}


def _ns(token: str) -> str:
    return token.split(":", 1)[0]


def _weight(token: str) -> int:
    return NAMESPACE_WEIGHTS.get(_ns(token), 1)


def weighted_jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter_w = sum(_weight(t) for t in a & b)
    union_w = sum(_weight(t) for t in a | b)
    return inter_w / union_w if union_w else 0.0


def _replace_tokens(conn: sqlite3.Connection, article_id: int, tokens: list[str]) -> None:
    conn.execute("DELETE FROM article_tokens WHERE article_id = ?", (article_id,))
    if tokens:
        conn.executemany(
            "INSERT OR IGNORE INTO article_tokens(token, article_id) VALUES (?, ?)",
            [(t, article_id) for t in tokens],
        )


def _candidate_ids(
    conn: sqlite3.Connection,
    article_id: int,
    tokens: list[str],
) -> list[tuple[int, int]]:
    """Return (article_id, shared_count) candidates from the inverted index."""
    if not tokens:
        return []
    s = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=s.cluster_window_days)
    placeholders = ",".join("?" * len(tokens))
    rows = conn.execute(
        f"""
        SELECT at.article_id, COUNT(*) AS shared
          FROM article_tokens at
          JOIN articles a ON a.id = at.article_id
         WHERE at.token IN ({placeholders})
           AND a.id != ?
           AND a.published_at IS NOT NULL
           AND a.published_at > ?
         GROUP BY at.article_id
        HAVING shared >= ?
         ORDER BY shared DESC
         LIMIT 50
        """,
        (*tokens, article_id, cutoff, s.cluster_min_shared),
    ).fetchall()
    return [(r["article_id"], r["shared"]) for r in rows]


def _tokens_for(conn: sqlite3.Connection, article_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT token FROM article_tokens WHERE article_id = ?", (article_id,)
    ).fetchall()
    return {r["token"] for r in rows}


def assign_constellation(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    tokens: list[str],
) -> tuple[int, float]:
    """Persist tokens, find/create the right cluster, return (cluster_id, sim)."""
    s = get_settings()
    _replace_tokens(conn, article_id, tokens)
    token_set = set(tokens)

    candidates = _candidate_ids(conn, article_id, tokens)

    best_cluster: int | None = None
    best_sim: float = 0.0

    for cand_id, _shared in candidates:
        cand_tokens = _tokens_for(conn, cand_id)
        sim = weighted_jaccard(token_set, cand_tokens)
        if sim < s.cluster_sim_threshold:
            continue
        cand_cluster_row = conn.execute(
            "SELECT story_cluster_id FROM articles WHERE id = ?", (cand_id,)
        ).fetchone()
        cand_cluster = cand_cluster_row["story_cluster_id"] if cand_cluster_row else None
        if cand_cluster is None:
            continue
        if sim > best_sim:
            best_sim = sim
            best_cluster = cand_cluster

    now = datetime.now(timezone.utc)
    if best_cluster is not None:
        conn.execute(
            "UPDATE articles SET story_cluster_id = ?, cluster_similarity = ? WHERE id = ?",
            (best_cluster, best_sim, article_id),
        )
        conn.execute(
            "UPDATE story_clusters SET last_seen_at = ?, member_count = member_count + 1 "
            "WHERE id = ?",
            (now, best_cluster),
        )
        return best_cluster, best_sim

    cur = conn.execute(
        "INSERT INTO story_clusters (representative_article_id, first_seen_at, "
        "last_seen_at, member_count) VALUES (?, ?, ?, 1)",
        (article_id, now, now),
    )
    cluster_id = int(cur.lastrowid)
    conn.execute(
        "UPDATE articles SET story_cluster_id = ?, cluster_similarity = NULL WHERE id = ?",
        (cluster_id, article_id),
    )
    return cluster_id, 1.0


def shared_tokens(a: set[str], b: set[str]) -> list[str]:
    """Return shared tokens sorted by weight (descending) for UI display."""
    return sorted(a & b, key=lambda t: (-_weight(t), t))
