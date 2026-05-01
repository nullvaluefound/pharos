-- Migration 0003: report generation history.
--
-- Stores the user's generated threat-intel reports so they can be revisited,
-- shared, or re-rendered later without re-running the LLM. Body is stored as
-- markdown; the frontend renders it.

CREATE TABLE IF NOT EXISTS reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    -- The generation request that produced the report (search filter, length,
    -- audience, structure choice, etc.) -- JSON.
    request_json    TEXT NOT NULL,
    -- The summary of what was actually fed to the model (count + IDs).
    article_ids_json TEXT NOT NULL DEFAULT '[]',
    article_count   INTEGER NOT NULL DEFAULT 0,
    -- Final markdown body returned by the LLM.
    body_md         TEXT NOT NULL DEFAULT '',
    -- "BLUF" | "custom"
    structure_kind  TEXT NOT NULL DEFAULT 'BLUF',
    -- "executive" | "technical" | "both"
    audience        TEXT NOT NULL DEFAULT 'both',
    -- "short" (1-2 pages) | "medium" (2-3) | "long" (3-4)
    length_target   TEXT NOT NULL DEFAULT 'short',
    -- "pending" | "generating" | "ready" | "failed"
    status          TEXT NOT NULL DEFAULT 'ready',
    error           TEXT,
    -- Cost estimate (USD) reported by the OpenAI call.
    cost_usd        REAL,
    model           TEXT,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at    DATETIME
);

CREATE INDEX IF NOT EXISTS idx_reports_user_created
    ON reports(user_id, created_at DESC);

INSERT OR REPLACE INTO schema_version(version) VALUES (3);
