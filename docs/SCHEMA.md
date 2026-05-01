# Database Schema

Pharos uses two SQLite files:

- `hot.db` — recent articles + all operational state.
- `cold.db` — archived articles ("the archeion").

The canonical DDL lives in
[`backend/pharos/db/schema_hot.sql`](../backend/pharos/db/schema_hot.sql)
and [`backend/pharos/db/schema_cold.sql`](../backend/pharos/db/schema_cold.sql).
This document is the human-readable companion.

Both DBs run with `journal_mode=WAL` and `foreign_keys=ON`. The API
opens `hot.db` and `ATTACH`es `cold.db` as schema `cold`, exposing a
`TEMP VIEW all_articles` that unions both for read paths.

## hot.db

### `users`
| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `username` | TEXT UNIQUE | |
| `password_hash` | TEXT | bcrypt |
| `is_admin` | INTEGER | 0/1 |
| `created_at` | DATETIME | default `CURRENT_TIMESTAMP` |
| `settings_json` | TEXT | per-user prefs (free-form) |

### `feeds`
One row per source URL, shared across users.

| column | notes |
|---|---|
| `id` | PK |
| `url` | UNIQUE |
| `title`, `site_url` | extracted from feed metadata |
| `etag`, `last_modified` | for conditional GET |
| `poll_interval_sec` | per-feed cadence |
| `last_polled_at`, `last_status`, `error_count` | health |

### `subscriptions`
Per-user link to a feed.

| column | notes |
|---|---|
| `(user_id, feed_id)` | composite PK |
| `folder` | optional user-defined grouping |
| `custom_title` | overrides `feeds.title` for this user |

### `articles`
One row per unique article URL, shared across users.

| column | notes |
|---|---|
| `id` | PK |
| `feed_id` | FK -> `feeds` |
| `url` | UNIQUE (canonicalized) |
| `url_hash` | SHA-256 of canonical URL (indexed) |
| `content_hash` | 64-bit SimHash hex (indexed) |
| `title`, `author`, `published_at`, `fetched_at` | metadata |
| `raw_text` | extracted body; cleared when archived |
| `raw_html_path` | optional blob path; cleared when archived |
| `enriched_json` | full LLM output (validated `EnrichedArticle`) |
| `overview` | short LLM summary, denormalized for fast list views |
| `language`, `severity_hint` | denormalized from `enriched_json` |
| `enrichment_status` | `pending \| in_progress \| enriched \| failed \| archived` |
| `enrichment_error` | last error message if `failed` |
| `fingerprint` | JSON array of namespaced tokens (see [LANTERN.md](./LANTERN.md)) |
| `story_cluster_id` | FK -> `story_clusters` (the constellation) |
| `cluster_similarity` | weighted Jaccard score vs. cluster representative |

Indexes: `(feed_id, published_at DESC)`, `(enrichment_status, fetched_at)`,
`(story_cluster_id)`, `url_hash`, `content_hash`, `published_at DESC`.

### `articles_fts`
FTS5 virtual table over `(title, overview, entities)`. The lantern
maintains it after each enrichment.

### `user_article_state`
Per-user read/saved state.

| column | notes |
|---|---|
| `(user_id, article_id)` | composite PK |
| `is_read`, `is_saved` | 0/1 |
| `read_at`, `saved_at` | timestamps |

### `entities`
Normalized entity catalog.

| column | notes |
|---|---|
| `id` | PK |
| `type` | one of: `threat_actor`, `malware`, `tool`, `vendor`, `company`, `product`, `cve`, `mitre_group`, `mitre_software`, `ttp_mitre`, `mitre_tactic`, `sector`, `country`, `topic` |
| `canonical_name` | lowercase normalized form |
| `display_name` | original casing as the LLM produced it |
| `aliases_json` | optional JSON array of alternate names |
| `(type, canonical_name)` | UNIQUE |

### `article_entities`
Join table linking an article to the entities it mentions.

| column | notes |
|---|---|
| `(article_id, entity_id)` | composite PK |
| `confidence` | float 0..1 |
| `role` | optional per-entity role (e.g. company `victim`/`vendor`) |

### `article_tokens`
Inverted index used by the constellation clusterer.

| column | notes |
|---|---|
| `(token, article_id)` | composite PK |

Tokens are namespaced strings like `mtg:g0016`, `cve:cve-2024-12345`,
`ttp:t1566.001`, `w:phishing`. See [LANTERN.md](./LANTERN.md) for the full
namespace list.

### `story_clusters`
The "constellations".

| column | notes |
|---|---|
| `id` | PK |
| `representative_article_id` | the seed article |
| `first_seen_at`, `last_seen_at` | bookkeeping |
| `member_count` | denormalized for fast UI badges |

### `saved_searches` (a.k.a. "watches")
| column | notes |
|---|---|
| `id` | PK |
| `user_id` | FK |
| `name` | display name |
| `query_json` | a `SearchQuery` JSON blob (see [API.md](./API.md)) |
| `notify` | 0/1 (notification hook is not implemented yet) |

## cold.db

Mirrors `articles`, `article_entities`, `article_tokens`, `story_clusters`
from the hot DB, but:

- No `raw_text`, no `raw_html_path` (raw bytes are dropped).
- No `user_article_state` (stays in hot.db for fast per-user filtering).
- An `archived_at` column records when the row was moved.
- Each `article` has `enrichment_status='archived'`.

The same FTS5 table exists in cold.db and is populated during the move.

## The unified read view

```sql
ATTACH DATABASE 'cold.db' AS cold;

CREATE TEMP VIEW all_articles AS
    SELECT id, feed_id, url, ..., 'hot' AS tier  FROM main.articles
    UNION ALL
    SELECT id, feed_id, url, ..., 'cold' AS tier FROM cold.articles;
```

Every read endpoint that doesn't care about hot-only state (e.g. stream,
search, related) selects from `all_articles` so the user never knows
where a given article physically lives.

## Migrations

The schema files are idempotent (`CREATE ... IF NOT EXISTS`) and `pharos
init` is safe to re-run after every upgrade. A simple `schema_version`
table lives in each DB to support future migrations; for now it just
records `1`.
