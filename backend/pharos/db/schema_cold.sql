-- Pharos cold database schema ("the archeion").
-- Mirrors hot.articles, article_entities, article_tokens, story_clusters
-- but without raw_text/raw_html_path and without per-user state.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS articles (
    id                  INTEGER PRIMARY KEY,
    feed_id             INTEGER NOT NULL,
    url                 TEXT NOT NULL UNIQUE,
    url_hash            TEXT NOT NULL,
    content_hash        TEXT,
    title               TEXT,
    author              TEXT,
    published_at        DATETIME,
    fetched_at          DATETIME NOT NULL,
    enriched_json       TEXT,
    overview            TEXT,
    language            TEXT,
    severity_hint       TEXT,
    enrichment_status   TEXT NOT NULL DEFAULT 'archived',
    fingerprint         TEXT,
    story_cluster_id    INTEGER,
    cluster_similarity  REAL,
    archived_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cold_articles_feed_pub ON articles(feed_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_cold_articles_cluster ON articles(story_cluster_id);
CREATE INDEX IF NOT EXISTS idx_cold_articles_published ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_cold_articles_url_hash ON articles(url_hash);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title,
    overview,
    entities,
    content=''
);

CREATE TABLE IF NOT EXISTS article_entities (
    article_id  INTEGER NOT NULL,
    entity_id   INTEGER NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,
    role        TEXT,
    PRIMARY KEY (article_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_cold_ae_entity ON article_entities(entity_id, article_id);

CREATE TABLE IF NOT EXISTS article_tokens (
    token       TEXT NOT NULL,
    article_id  INTEGER NOT NULL,
    PRIMARY KEY (token, article_id)
);

CREATE INDEX IF NOT EXISTS idx_cold_atok_article ON article_tokens(article_id);

CREATE TABLE IF NOT EXISTS story_clusters (
    id                          INTEGER PRIMARY KEY,
    representative_article_id   INTEGER,
    first_seen_at               DATETIME NOT NULL,
    last_seen_at                DATETIME NOT NULL,
    member_count                INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version(version) VALUES (1);
