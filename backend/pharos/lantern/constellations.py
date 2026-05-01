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
# STRONG ANCHORS (per-event identifiers, very rarely co-occur on different
# stories within a 2-week window):
#   cve   CVE identifier (CVE-YYYY-NNNNN)
#   mtg   MITRE Group ID (G####)        -- canonical actor
#   mts   MITRE Software ID (S####)     -- canonical malware/tool
#   thr   Threat actor canonical name (e.g. "lazarus")
#   mal   Malware canonical name (e.g. "beavertail")
#
# WEAK ANCHORS (per-vendor/company/product identifiers; common enough that
# template content ("Apple Daily", "NYT Connections") can falsely cluster
# on them, so the gate requires either >=2 of these OR pairing with at
# least one strong anchor OR meaningful context overlap):
#   ven   Vendor (e.g. "anthropic", "cisco")
#   com   Company (the targeted/affected org, e.g. "bybit")
#   pro   Product (e.g. "claude-mythos", "exchange-server")
#
# CONTEXT (broad, dilute signal -- bag-of-words tail and taxonomy):
#   tool  generic tooling
#   sec   sector
#   geo   country
#   top   topic
#   w     bag-of-words tail
#
# MITRE Techniques (ttp) and Tactics (mta) are NOT in this map -- they are
# excluded from the fingerprint entirely (see fingerprint.py).
NAMESPACE_WEIGHTS: dict[str, int] = {
    # strong anchors -- dominate similarity
    "cve":  15,
    "mtg":  12,
    "mts":  12,
    "thr":  10,
    "mal":  10,
    # weak anchors
    "ven":   6,
    "com":   6,
    "pro":   6,
    # context
    "tool":  2,
    "sec":   1,
    "geo":   1,
    "top":   1,
    "w":     1,
}

STRONG_ANCHORS: frozenset[str] = frozenset({"cve", "mtg", "mts", "thr", "mal"})
WEAK_ANCHORS:   frozenset[str] = frozenset({"ven", "com", "pro"})
ANCHOR_NAMESPACES: frozenset[str] = STRONG_ANCHORS | WEAK_ANCHORS

# Minimum bag-of-words / topic / sector / geo Jaccard required when ONLY
# weak anchors overlap. Defeats template false positives like "9to5Mac
# Daily roundup" or "NYT Connections puzzle of the day" where the same
# brand mentions recur but the actual content is different every day.
_WEAK_ONLY_CONTEXT_FLOOR = 0.10

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


def _context_jaccard(a: set[str], b: set[str]) -> float:
    """Plain (un-weighted) Jaccard over non-anchor tokens only."""
    a_ctx = {t for t in a if _ns(t) not in ANCHOR_NAMESPACES}
    b_ctx = {t for t in b if _ns(t) not in ANCHOR_NAMESPACES}
    if not a_ctx and not b_ctx:
        return 0.0
    inter = a_ctx & b_ctx
    union = a_ctx | b_ctx
    return len(inter) / len(union) if union else 0.0


def has_anchor_overlap(a: set[str], b: set[str]) -> bool:
    """Backwards-compatible: True iff ``a`` and ``b`` share >=1 anchor token.

    Used by tests + the API ``/articles/{id}/related`` endpoint. The full
    cluster gate that also considers context lives in
    :func:`should_consider_cluster`.
    """
    return any(_ns(t) in ANCHOR_NAMESPACES for t in a & b)


def should_consider_cluster(a: set[str], b: set[str]) -> bool:
    """The actual cluster gate. Returns True when ``a`` and ``b`` are
    eligible to be evaluated for clustering.

    Rules:
      * They share >=1 STRONG anchor (cve / mtg / mts / thr / mal), OR
      * They share >=2 WEAK anchors AND have non-trivial context overlap
        (catches Bloomberg/Gizmodo on same M&A story; rejects
        9to5Mac-Daily-style template duplicates).
    """
    a = _filter_active(a)
    b = _filter_active(b)
    shared = a & b
    if not shared:
        return False
    n_strong = sum(1 for t in shared if _ns(t) in STRONG_ANCHORS)
    if n_strong >= 1:
        return True
    n_weak = sum(1 for t in shared if _ns(t) in WEAK_ANCHORS)
    if n_weak >= 2 and _context_jaccard(a, b) >= _WEAK_ONLY_CONTEXT_FLOOR:
        return True
    return False


def weighted_jaccard(a: set[str], b: set[str]) -> float:
    """Weighted Jaccard over ALL active tokens.

    Used by the related-articles UI to render a soft 0..1 similarity
    between two articles. NOT used for the cluster decision itself --
    see :func:`anchor_jaccard` for that.
    """
    a = _filter_active(a)
    b = _filter_active(b)
    if not a or not b:
        return 0.0
    inter_w = sum(_weight(t) for t in a & b)
    union_w = sum(_weight(t) for t in a | b)
    return inter_w / union_w if union_w else 0.0


def anchor_jaccard(a: set[str], b: set[str]) -> float:
    """Weighted Jaccard restricted to ANCHOR namespaces only.

    Why we don't include the bag-of-words tail in the cluster decision:
    two outlets covering the same vulnerability often pick wildly
    different angles ("cryptographic subsystem" vs. "live process code
    injection" vs. "Python PoC"). Their bag-of-words barely overlaps,
    so a full-token weighted Jaccard scores ~0.20 even when the CVE
    matches perfectly. That collapses what should be one cluster into
    dozens of singletons.

    Anchor-only scoring concentrates the signal where it actually lives
    (per-event identifiers) and lets the threshold do its job.
    """
    a_anc = {t for t in a if _ns(t) in ANCHOR_NAMESPACES}
    b_anc = {t for t in b if _ns(t) in ANCHOR_NAMESPACES}
    if not a_anc or not b_anc:
        return 0.0
    inter_w = sum(_weight(t) for t in a_anc & b_anc)
    union_w = sum(_weight(t) for t in a_anc | b_anc)
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
    *,
    as_of: datetime | None = None,
) -> list[tuple[int, int]]:
    """Return (article_id, shared_anchor_count) candidates from the inverted index.

    Candidate generation is restricted to the article's ANCHOR tokens -- if
    nothing in our anchor set appears in any other recent article, we have no
    candidates. This makes false-positive clusters structurally impossible.

    ``as_of`` anchors the candidate window. For live enrichment of just-arrived
    articles this is "now" (the default). For chronological rebuilds it's the
    article's own ``published_at`` so each article looks back the proper number
    of days into HISTORY rather than into the recent calendar past.
    """
    anchors = [t for t in tokens if _ns(t) in ANCHOR_NAMESPACES]
    if not anchors:
        return []
    s = get_settings()
    pivot = as_of if as_of is not None else datetime.now(timezone.utc)
    # Guard against corrupted timestamps in the corpus that would
    # underflow / overflow timedelta arithmetic (some RSS feeds publish
    # year-0001 / year-9999 dates).
    delta = timedelta(days=s.cluster_window_days)
    try:
        lower = pivot - delta
    except (OverflowError, ValueError):
        lower = datetime.min.replace(tzinfo=pivot.tzinfo)
    try:
        upper = pivot + delta
    except (OverflowError, ValueError):
        upper = datetime.max.replace(tzinfo=pivot.tzinfo)
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
           AND a.published_at < ?
         GROUP BY at.article_id
         ORDER BY shared DESC
         LIMIT 200
        """,
        (*anchors, article_id, lower, upper),
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
    published_at: datetime | None = None,
) -> tuple[int, float]:
    """Persist tokens, find/create the right cluster, return (cluster_id, sim).

    ``published_at`` should be the article's publication timestamp. It pins
    the candidate-window pivot so historical / out-of-order articles look
    back into HISTORY around their own publish date rather than around the
    current wall-clock time. Defaults to None which means "use now()".
    """
    s = get_settings()
    _replace_tokens(conn, article_id, tokens)
    token_set = _filter_active(set(tokens))

    candidates = _candidate_ids(conn, article_id, tokens, as_of=published_at)

    best_cluster: int | None = None
    best_sim: float = 0.0

    for cand_id, _shared in candidates:
        cand_tokens = _tokens_for(conn, cand_id)
        # Hard gate: at least one strong per-event identifier in common,
        # OR multiple weak anchors backed by some context overlap.
        if not should_consider_cluster(token_set, cand_tokens):
            continue
        # Anchor-only similarity for the threshold decision -- bag-of-words
        # dilutes the union too aggressively when two outlets cover the
        # same event with different angles. See anchor_jaccard() docstring.
        sim = anchor_jaccard(token_set, cand_tokens)
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
