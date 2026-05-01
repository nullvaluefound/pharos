"""The lantern worker: pulls pending articles, runs LLM enrichment,
persists the structured output, builds fingerprints, and assigns
constellations.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from ..config import get_settings
from ..db import connect
from . import malpedia
from .constellations import assign_constellation
from .fingerprint import build_fingerprint
from .llm_client import LanternLLMError, enrich
from .schema import EnrichedArticle

log = logging.getLogger(__name__)

# Entity-type to (table column / token namespace) mapping for normalized rows.
ENTITY_TYPE_MAP = {
    "threat_actor": "threat_actors",
    "malware": "malware",
    "tool": "tools",
    "vendor": "vendors",
    "company": "companies",
    "product": "products",
    "cve": "cves",
    "ttp_mitre": "ttps_mitre",
    "sector": "sectors",
    "country": "countries",
    "topic": "topics",
}


def _upsert_entity(
    conn: sqlite3.Connection, *, type_: str, name: str
) -> int:
    canonical = name.strip().lower()
    if not canonical:
        return 0
    row = conn.execute(
        "SELECT id FROM entities WHERE type = ? AND canonical_name = ?",
        (type_, canonical),
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO entities (type, canonical_name, display_name) VALUES (?, ?, ?)",
        (type_, canonical, name.strip()),
    )
    return int(cur.lastrowid)


def _persist_entities(
    conn: sqlite3.Connection,
    article_id: int,
    enriched: EnrichedArticle,
) -> list[str]:
    """Insert article_entities rows; return entity display names for FTS."""
    entity_names: list[str] = []
    e = enriched.entities

    def add(type_: str, name: str, role: str | None = None, conf: float = 1.0) -> None:
        if not name:
            return
        eid = _upsert_entity(conn, type_=type_, name=name)
        if not eid:
            return
        conn.execute(
            "INSERT OR REPLACE INTO article_entities "
            "(article_id, entity_id, confidence, role) VALUES (?, ?, ?, ?)",
            (article_id, eid, conf, role),
        )
        entity_names.append(name)

    for ne in e.threat_actors:
        add("threat_actor", ne.name, conf=ne.confidence)
        if ne.mitre_group_id:
            add("mitre_group", ne.mitre_group_id, conf=ne.confidence)
    for ne in e.malware:
        add("malware", ne.name, conf=ne.confidence)
        if ne.mitre_software_id:
            add("mitre_software", ne.mitre_software_id, conf=ne.confidence)
    for ne in e.tools:
        add("tool", ne.name, conf=ne.confidence)
    for ne in e.vendors:
        add("vendor", ne.name, conf=ne.confidence)
    for ce in e.companies:
        add("company", ce.name, role=ce.role, conf=ce.confidence)
    for pe in e.products:
        add("product", pe.name, conf=pe.confidence)
    for cve in e.cves:
        add("cve", cve)
    for ttp in e.ttps_mitre:
        add("ttp_mitre", ttp)
    for gid in e.mitre_groups:
        add("mitre_group", gid)
    for sid in e.mitre_software:
        add("mitre_software", sid)
    for tid in e.mitre_tactics:
        add("mitre_tactic", tid)
    for sector in e.sectors:
        add("sector", sector)
    for country in e.countries:
        add("country", country)
    for topic in enriched.topics:
        add("topic", topic)

    return entity_names


def _refresh_fts(
    conn: sqlite3.Connection,
    article_id: int,
    title: str | None,
    overview: str,
    entity_names: list[str],
) -> None:
    # contentless FTS5 tables don't support DELETE, so ignore failures
    try:
        conn.execute("DELETE FROM articles_fts WHERE rowid = ?", (article_id,))
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "INSERT INTO articles_fts(rowid, title, overview, entities) VALUES (?, ?, ?, ?)",
            (article_id, title or "", overview or "", " ".join(entity_names)),
        )
    except sqlite3.IntegrityError:
        pass


def _canonicalize(enriched: EnrichedArticle) -> EnrichedArticle:
    """Run Malpedia post-processing on an EnrichedArticle.

    We dump to a plain dict, mutate the entity lists, then re-validate so
    Pydantic's per-field validators (CVE normalization, MITRE Group
    format check, etc.) run a second time on whatever we changed.
    """
    data = enriched.model_dump()
    e = data.get("entities") or {}

    actors_in = e.get("threat_actors") or []
    actors_out, extra_group_ids = malpedia.canonicalize_actors(actors_in)
    e["threat_actors"] = actors_out

    malware_in = e.get("malware") or []
    malware_out, extra_software_ids = malpedia.canonicalize_malware(malware_in)
    e["malware"] = malware_out

    e["mitre_groups"] = malpedia.merge_id_lists(
        e.get("mitre_groups") or [],
        extra_group_ids,
    )
    e["mitre_software"] = malpedia.merge_id_lists(
        e.get("mitre_software") or [],
        extra_software_ids,
    )

    data["entities"] = e
    try:
        return EnrichedArticle.model_validate(data)
    except Exception as exc:
        log.warning(
            "Malpedia canonicalization produced invalid entities, falling "
            "back to original (reason=%s)", exc
        )
        return enriched


async def _process_one(row: sqlite3.Row) -> None:
    aid = int(row["id"])
    title = row["title"]
    url = row["url"]
    body = row["raw_text"] or ""
    published_raw = row["published_at"] if "published_at" in row.keys() else None
    published_at: datetime | None = None
    if published_raw is not None:
        if isinstance(published_raw, datetime):
            published_at = published_raw
        else:
            try:
                published_at = datetime.fromisoformat(
                    str(published_raw).replace("Z", "+00:00")
                )
            except ValueError:
                published_at = None

    try:
        enriched = await enrich(title=title, url=url, body=body)
    except LanternLLMError as exc:
        log.warning("enrichment failed for article %s: %s", aid, exc)
        with connect(attach_cold=False) as conn:
            conn.execute(
                "UPDATE articles SET enrichment_status = 'failed', "
                "enrichment_error = ? WHERE id = ?",
                (str(exc)[:1000], aid),
            )
            conn.commit()
        return

    enriched = _canonicalize(enriched)

    fingerprint = build_fingerprint(enriched, title=title)
    enriched_json = enriched.model_dump_json()

    with connect(attach_cold=False) as conn:
        try:
            conn.execute("BEGIN")
            conn.execute(
                "UPDATE articles SET enriched_json = ?, overview = ?, language = ?, "
                "severity_hint = ?, fingerprint = ?, enrichment_status = 'enriched', "
                "enrichment_error = NULL WHERE id = ?",
                (
                    enriched_json,
                    enriched.overview,
                    enriched.language,
                    enriched.severity_hint,
                    json.dumps(fingerprint),
                    aid,
                ),
            )
            entity_names = _persist_entities(conn, aid, enriched)
            _refresh_fts(conn, aid, title, enriched.overview, entity_names)
            assign_constellation(
                conn,
                article_id=aid,
                tokens=fingerprint,
                published_at=published_at,
            )
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            log.exception("post-enrichment persistence failed for %s: %s", aid, exc)
            conn.execute(
                "UPDATE articles SET enrichment_status = 'failed', "
                "enrichment_error = ? WHERE id = ?",
                (f"persist_error: {exc}"[:1000], aid),
            )
            conn.commit()
            return

    log.info("enriched article %s (%s)", aid, title)


def _claim_pending(limit: int) -> list[sqlite3.Row]:
    """Atomically claim a batch of pending articles by flipping a marker.

    SQLite has no SELECT FOR UPDATE; we approximate by updating rows in a
    transaction and returning them. Workers race safely because the WHERE
    clause filters on the previous status.
    """
    with connect(attach_cold=False) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id, url, title, raw_text, published_at FROM articles "
            "WHERE enrichment_status = 'pending' "
            "ORDER BY fetched_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            conn.execute("COMMIT")
            return []
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE articles SET enrichment_status = 'in_progress' "
            f"WHERE id IN ({placeholders})",
            ids,
        )
        conn.execute("COMMIT")
    return rows


async def run_forever() -> None:
    s = get_settings()
    logging.basicConfig(level=s.log_level)
    sem = asyncio.Semaphore(s.lantern_concurrency)

    async def _bounded(row: sqlite3.Row) -> None:
        async with sem:
            await _process_one(row)

    log.info("lantern worker started (model=%s, concurrency=%d)",
             s.openai_model, s.lantern_concurrency)
    while True:
        rows = _claim_pending(s.lantern_batch)
        if not rows:
            await asyncio.sleep(s.lantern_poll_interval_sec)
            continue
        await asyncio.gather(*[_bounded(r) for r in rows])
