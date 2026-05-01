-- Pharos hot database schema.
-- Holds users, feeds, subscriptions, recent articles (<= ARCHIVE_AFTER_DAYS),
-- enrichment outputs, per-user state, the inverted token index, and
-- saved searches ("watches").

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    is_admin        INTEGER NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    settings_json   TEXT NOT NULL DEFAULT '{}'
);

-- ---------------------------------------------------------------------------
-- Feeds (shared across users; subscriptions link users to feeds)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feeds (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    url                 TEXT NOT NULL UNIQUE,
    title               TEXT,
    site_url            TEXT,
    etag                TEXT,
    last_modified       TEXT,
    poll_interval_sec   INTEGER NOT NULL DEFAULT 900,
    last_polled_at      DATETIME,
    last_status         TEXT,
    error_count         INTEGER NOT NULL DEFAULT 0,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feeds_last_polled ON feeds(last_polled_at);

-- ---------------------------------------------------------------------------
-- Subscriptions (per-user)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feed_id         INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    folder          TEXT NOT NULL DEFAULT '',
    custom_title    TEXT,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, feed_id)
);

CREATE INDEX IF NOT EXISTS idx_subs_feed ON subscriptions(feed_id);

-- ---------------------------------------------------------------------------
-- Articles (one row per unique article; shared across users)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS articles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id             INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    url                 TEXT NOT NULL UNIQUE,
    url_hash            TEXT NOT NULL,
    content_hash        TEXT,
    title               TEXT,
    author              TEXT,
    published_at        DATETIME,
    fetched_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_text            TEXT,                       -- extracted readable text (cleared on archive)
    raw_html_path       TEXT,                       -- optional blob path
    enriched_json       TEXT,                       -- full LLM output as JSON
    overview            TEXT,                       -- denormalized short summary
    language            TEXT,
    severity_hint       TEXT,
    enrichment_status   TEXT NOT NULL DEFAULT 'pending'
                            CHECK (enrichment_status IN
                                   ('pending','in_progress','enriched','failed','archived')),
    enrichment_error    TEXT,
    fingerprint         TEXT,                       -- JSON array of tokens
    story_cluster_id    INTEGER,
    cluster_similarity  REAL
);

CREATE INDEX IF NOT EXISTS idx_articles_feed_pub ON articles(feed_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(enrichment_status, fetched_at);
CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(story_cluster_id);
CREATE INDEX IF NOT EXISTS idx_articles_url_hash ON articles(url_hash);
CREATE INDEX IF NOT EXISTS idx_articles_content_hash ON articles(content_hash);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);

-- ---------------------------------------------------------------------------
-- Full-text search (FTS5) over title + overview + entity names
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title,
    overview,
    entities,
    content=''
);

-- ---------------------------------------------------------------------------
-- Per-user article state
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_article_state (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_id  INTEGER NOT NULL,
    is_read     INTEGER NOT NULL DEFAULT 0,
    is_saved    INTEGER NOT NULL DEFAULT 0,
    read_at     DATETIME,
    saved_at    DATETIME,
    PRIMARY KEY (user_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_uas_saved ON user_article_state(user_id, is_saved, saved_at DESC);

-- ---------------------------------------------------------------------------
-- Entities (normalized for fast filtering).
-- type in:
--   threat_actor    -- canonical actor name (e.g. "APT29", "Lazarus Group")
--   malware         -- canonical malware name (e.g. "Cobalt Strike")
--   tool            -- offensive/defensive tool (free text)
--   vendor          -- product vendor (e.g. "Microsoft")
--   company         -- any company appearing in the article
--   product         -- product/service name
--   cve             -- CVE identifier (e.g. "CVE-2024-12345")
--   mitre_group     -- MITRE ATT&CK Group ID (G####, e.g. G0016 = APT29)
--   mitre_software  -- MITRE ATT&CK Software ID (S####, e.g. S0154 = Cobalt Strike)
--   ttp_mitre       -- MITRE Technique / Sub-technique ID (T####, T####.###)
--   mitre_tactic    -- MITRE Tactic ID (TA####)
--   sector          -- industry sector (lowercase noun, e.g. "finance")
--   country         -- ISO-3166 alpha-2 country code (e.g. "US")
--   topic           -- free-text topic tag
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type            TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    aliases_json    TEXT NOT NULL DEFAULT '[]',
    UNIQUE (type, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

CREATE TABLE IF NOT EXISTS article_entities (
    article_id  INTEGER NOT NULL,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    confidence  REAL NOT NULL DEFAULT 1.0,
    role        TEXT,
    PRIMARY KEY (article_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_ae_entity ON article_entities(entity_id, article_id);

-- ---------------------------------------------------------------------------
-- Inverted token index (for deterministic constellation clustering)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS article_tokens (
    token       TEXT NOT NULL,
    article_id  INTEGER NOT NULL,
    PRIMARY KEY (token, article_id)
);

CREATE INDEX IF NOT EXISTS idx_atok_article ON article_tokens(article_id);

-- ---------------------------------------------------------------------------
-- Story clusters ("constellations")
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS story_clusters (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    representative_article_id   INTEGER,
    first_seen_at               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    member_count                INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------------
-- Saved searches ("watches")
-- query_json structure:
--   {
--     "any_of":   {"threat_actors": [...], "cves": [...], ...},
--     "all_of":   {"sectors": [...]},
--     "none_of":  {"vendors": [...]},
--     "text":     "...",
--     "since_days": 14,
--     "feeds":    [feed_id, ...]
--   }
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS saved_searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    query_json  TEXT NOT NULL,
    notify      INTEGER NOT NULL DEFAULT 0,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_watches_user ON saved_searches(user_id);

-- ---------------------------------------------------------------------------
-- In-app notifications (delivered when watches match new articles)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    watch_id    INTEGER REFERENCES saved_searches(id) ON DELETE SET NULL,
    article_id  INTEGER,
    title       TEXT NOT NULL,
    body        TEXT,
    is_read     INTEGER NOT NULL DEFAULT 0,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, watch_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_notifications_user
    ON notifications(user_id, is_read, created_at DESC);

-- Track which articles a watch has already triggered so we only notify once.
CREATE TABLE IF NOT EXISTS watch_seen_articles (
    watch_id    INTEGER NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
    article_id  INTEGER NOT NULL,
    seen_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (watch_id, article_id)
);

-- ---------------------------------------------------------------------------
-- User-defined feed folders (allows empty folders to exist)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_folders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_uf_user ON user_folders(user_id);

-- ---------------------------------------------------------------------------
-- Schema version (simple bookkeeping)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version(version) VALUES (1);
