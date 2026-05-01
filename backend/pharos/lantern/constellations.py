"""Story-cluster ("constellation") assignment using anchor-gated weighted Jaccard.

Algorithm:
1. After enrichment, the article has a set of namespaced tokens (fingerprint).
2. We use the ``article_tokens`` inverted index in SQLite to find candidate
   articles published within ``CLUSTER_WINDOW_DAYS`` that share at least
   ``CLUSTER_MIN_SHARED`` tokens with the new article.
3. For each candidate we compute weighted Jaccard similarity. Per-event
   identifiers (CVE, MITRE Group/Software ID, canonical threat actor, malware,
   vendor, company, product) carry the strongest signal -- they're called
   "anchors" because each one usually identifies a single real-world incident.
4. **Cluster gate**: a candidate only counts if it shares at least one ANCHOR
   token with the new article. Two stories that share a hundred recon TTPs
   and the word "attacker" are NOT the same story -- only stories that
   reference the same CVE, the same actor group, the same malware family,
   etc. cluster together.
5. If the best (anchor-gated) similarity meets ``CLUSTER_SIM_THRESHOLD`` we
   attach the new article to that cluster; otherwise we create a new
   constellation.

This is fully deterministic and explainable -- the API exposes the matched
tokens through ``/articles/{id}/related``.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from ..config import get_settings

# Token-namespace weights. Keep in sync with prefixes in fingerprint.py.
#
# ANCHOR namespaces (per-event identifiers) -- big weights:
#   cve   CVE identifier (CVE-YYYY-NNNNN)
#   mtg   MITRE Group ID (G####)        -- canonical actor
#   mts   MITRE Software ID (S####)     -- canonical malware/tool
#   thr   Threat actor canonical name (e.g. "lazarus")
#   mal   Malware canonical name (e.g. "beavertail")
#   ven   Vendor (e.g. "anthropic", "cisco")
#   com   Company (the targeted/affected org, e.g. "bybit")
#   pro   Product (e.g. "claude-mythos", "exchange-server")
#
# CONTEXT namespaces (broad, often shared across unrelated stories):
#   tool  generic tooling
#   sec   sector
#   geo   country
#   top   topic
#   w     bag-of-words tail
#
# MITRE Techniques (ttp) and Tactics (mta) are NOT in this map -- they are
# excluded from the fingerprint entirely (see fingerprint.py).
NAMESPACE_WEIGHTS: dict[str, int] = {
    # anchors
    "cve":  10,
    "mtg":   8,
    "mts":   8,
    "thr":   7,
    "mal":   7,
    "ven":   5,
    "com":   5,
    "pro":   5,
    # context
    "tool":  2,
    "sec":   1,
    "geo":   1,
    "top":   1,
    "w":     1,
}

# Namespaces whose presence (overlap of >=1 token) signals a real per-event
# match. Without one of these in common, we refuse to cluster two articles.
ANCHOR_NAMESPACES: frozenset[str] = frozenset({
    "cve", "mtg", "mts", "thr", "mal", "ven", "com", "pro",
})

# Defensive: if old data still has ``ttp:`` / ``mta:`` rows in
# ``article_tokens``, ignore them everywhere.
_IGNORED_NAMESPACES: frozenset[str] = frozenset({"ttp", "mta"})


def _ns(token: str) -> str:
    return token.split(":", 1)[0]


def _weight(token: str) -> int:
    return NAMESPACE_WEIGHTS.get(_ns(token), 1)


def _filter_active(tokens: set[str]) -> set[str]:
    """Strip namespaces we no longer cluster on (e.g. ttp/mta legacy rows)."""
    return {t for t in tokens if _ns(t) not in _IGNORED_NAMESPACES}


def has_anchor_overlap(a: set[str], b: set[str]) -> bool:
    """Return True iff ``a`` and ``b`` share >=1 ANCHOR-namespace token."""
    for token in a & b:
        if _ns(token) in ANCHOR_NAMESPACES:
            return True
    return False


def weighted_jaccard(a: set[str], b: set[str]) -> float:
    a = _filter_active(a)
    b = _filter_active(b)
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
    """Return (article_id, shared_anchor_count) candidates from the inverted index.

    Candidate generation is restricted to the article's ANCHOR tokens -- if
    nothing in our anchor set appears in any other recent article, we have no
    candidates. This makes false-positive clusters structurally impossible.
    """
    anchors = [t for t in tokens if _ns(t) in ANCHOR_NAMESPACES]
    if not anchors:
        return []
    s = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=s.cluster_window_days)
    placeholders = ",".join("?" * len(anchors))
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
         ORDER BY shared DESC
         LIMIT 50
        """,
        (*anchors, article_id, cutoff),
    ).fetchall()
    return [(r["article_id"], r["shared"]) for r in rows]


def _tokens_for(conn: sqlite3.Connection, article_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT token FROM article_tokens WHERE article_id = ?", (article_id,)
    ).fetchall()
    return _filter_active({r["token"] for r in rows})


def assign_constellation(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    tokens: list[str],
) -> tuple[int, float]:
    """Persist tokens, find/create the right cluster, return (cluster_id, sim)."""
    s = get_settings()
    _replace_tokens(conn, article_id, tokens)
    token_set = _filter_active(set(tokens))

    candidates = _candidate_ids(conn, article_id, tokens)

    best_cluster: int | None = None
    best_sim: float = 0.0

    for cand_id, _shared in candidates:
        cand_tokens = _tokens_for(conn, cand_id)
        # Hard gate: must share at least one per-event identifier (CVE,
        # MITRE Group/Software, canonical actor/malware, vendor, company,
        # product). This is the single biggest false-positive killer.
        if not has_anchor_overlap(token_set, cand_tokens):
            continue
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
    inter = _filter_active(a) & _filter_active(b)
    return sorted(inter, key=lambda t: (-_weight(t), t))
