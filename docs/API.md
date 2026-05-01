# API Reference

All routes live under `/api/v1`. Auth is required on every route except
`POST /auth/login`, `POST /auth/register`, and `GET /healthz`.

Authentication: send `Authorization: Bearer <token>` **or** rely on the
`pharos_token` cookie that `POST /auth/login` sets.

For a live, machine-readable reference, the FastAPI app exposes
**`/docs`** (Swagger UI) and **`/openapi.json`** (OpenAPI 3 schema)
out of the box.

## Auth

### `POST /auth/login`
```json
{ "username": "alice", "password": "..." }
```
Returns a `TokenOut` and sets the `pharos_token` cookie:
```json
{
  "access_token": "...",
  "token_type": "bearer",
  "user_id": 1,
  "username": "alice",
  "is_admin": true
}
```

### `POST /auth/register`
Same body as `/login`. Returns a `TokenOut`. Returns `403` unless
`ALLOW_REGISTRATION=true`.

### `POST /auth/logout`
Clears the cookie.

### `GET /auth/me`
```json
{ "id": 1, "username": "alice", "is_admin": true }
```

## Feeds

### `GET /feeds`
Returns the current user's subscriptions:
```json
[
  {
    "id": 7, "url": "https://...", "title": "...", "site_url": "...",
    "folder": "Security", "custom_title": null,
    "last_polled_at": "2026-04-29T22:00:00Z",
    "last_status": "200", "error_count": 0
  }
]
```

### `POST /feeds`
```json
{ "url": "https://...", "folder": "Security", "custom_title": null }
```
Creates the feed if new, then subscribes the current user. Returns the
`FeedOut`.

### `DELETE /feeds/{feed_id}`
Removes the subscription (the feed itself stays so other users keep theirs).

## Stream

### `GET /stream`
Query params:
- `view`: `grouped` (default) or `flat`.
- `folder`: optional folder filter.
- `only_unread`, `only_saved`: booleans.
- `limit` (1..200, default 50).
- `cursor`: a `published_at` timestamp from the previous page's `next_cursor`.

`flat` returns:
```json
{ "view": "flat", "items": [ArticleSummary, ...], "next_cursor": "..." }
```

`grouped` returns:
```json
{
  "view": "grouped",
  "items": [
    {
      "cluster_id": 912,
      "member_count": 5,
      "representative": ArticleSummary,
      "other_sources": [ArticleSummary, ...]   // up to 5 siblings
    }
  ],
  "next_cursor": "..."
}
```

`ArticleSummary`:
```json
{
  "id": 4821, "feed_id": 7, "feed_title": "...", "url": "...",
  "title": "...", "author": "...", "published_at": "...",
  "overview": "...", "severity_hint": "high",
  "is_read": false, "is_saved": false,
  "story_cluster_id": 912, "tier": "hot"
}
```

## Articles

### `GET /articles/{id}`
Returns `ArticleDetail` (`ArticleSummary` + `enriched`):
```jsonc
{
  ...ArticleSummary fields,
  "enriched": {
    "overview": "...",
    "language": "en",
    "content_type": "advisory",
    "topics": ["ransomware", "supply_chain"],
    "key_points": ["..."],
    "severity_hint": "high",
    "entities": {
      "threat_actors": [{"name": "APT29", "mitre_group_id": "G0016"}],
      "malware": [{"name": "Cobalt Strike", "mitre_software_id": "S0154"}],
      "tools": [{"name": "Mimikatz"}],
      "vendors": [{"name": "Microsoft"}],
      "companies": [{"name": "Acme Corp", "role": "victim"}],
      "products": [{"name": "Exchange Server", "version": "2019"}],
      "cves": ["CVE-2024-12345"],
      "mitre_groups": ["G0016"],
      "mitre_software": ["S0154"],
      "ttps_mitre": ["T1566", "T1566.001"],
      "mitre_tactics": ["TA0001"],
      "iocs": { "ipv4": [], "domains": [], "sha256": [], "urls": [] },
      "sectors": ["finance"],
      "countries": ["US"],
      // Pharos decorates MITRE IDs with their attack.mitre.org URLs:
      "mitre_links": {
        "groups":     {"G0016": "https://attack.mitre.org/groups/G0016/"},
        "software":   {"S0154": "https://attack.mitre.org/software/S0154/"},
        "techniques": {"T1566.001": "https://attack.mitre.org/techniques/T1566/001/"},
        "tactics":    {"TA0001": "https://attack.mitre.org/tactics/TA0001/"}
      }
    }
  }
}
```

### `GET /articles/{id}/related`
Returns the constellation siblings (other articles covering the same
story), with the **`shared_tokens`** array that explains *why* they
clustered together:
```json
{
  "article_id": 4821,
  "cluster_id": 912,
  "members": [
    {
      "id": 4815, "feed_title": "TheRegister", "url": "...", "title": "...",
      "published_at": "...", "overview": "...",
      "similarity": 0.78,
      "shared_tokens": [
        "cve:cve-2024-12345", "mtg:g0016",
        "thr:apt29", "com:microsoft", "w:phishing"
      ]
    }
  ]
}
```

### `POST /articles/{id}/state`
```json
{ "is_read": true, "is_saved": true }
```
Either field is optional. Returns the new state.

## Search

### `POST /search`
Structured filter over the entity index + FTS5:
```json
{
  "any_of":  { "threat_actor": ["apt29"], "cve": ["cve-2024-12345"] },
  "all_of":  { "sector": ["finance"] },
  "none_of": { "vendor": ["vendor-i-dont-care"] },
  "text":    "supply chain",
  "since_days": 14,
  "feed_ids": [1, 2],
  "limit": 50
}
```
Entity-type keys for the `*_of` maps:

`threat_actor`, `malware`, `tool`, `vendor`, `company`, `product`,
`cve`, `mitre_group`, `mitre_software`, `ttp_mitre`, `mitre_tactic`,
`sector`, `country`, `topic`.

Names should be lowercase canonical (e.g. `"apt29"`, `"g0016"`,
`"cve-2024-12345"`, `"t1566.001"`).

Response:
```json
{ "hits": [SearchHit, ...], "count": 12 }
```

## Bookmarks

### `GET /bookmarks?limit=100`
Returns the user's saved articles.

## Watches (saved searches)

### `GET /watches`
Returns the user's saved searches.

### `POST /watches`
```json
{ "name": "APT29 in finance", "query": { ...same as /search... }, "notify": false }
```

### `DELETE /watches/{id}`

## Admin (requires `is_admin`)

### `GET /admin/pipeline`
```json
{
  "counts_by_status": { "pending": 12, "enriched": 4321, "failed": 2 },
  "feeds": 28, "subscriptions": 31, "users": 3, "cold_articles": 12450
}
```

### `POST /admin/reprocess`
```json
{ "article_ids": [1, 2, 3], "failed_only": false }
```
Resets `enrichment_status` to `pending` so the lantern picks them up again.

### `POST /admin/archive`
Triggers one archive pass.

### `GET /admin/feed-catalog`
Returns the bundled curated feed catalog (categories + presets):
```json
{
  "categories": [
    {
      "id": "government", "name": "Government & CERTs",
      "folder": "Government", "description": "...",
      "enabled_by_default": true,
      "feeds": [
        { "title": "CISA Cybersecurity Advisories",
          "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
          "folder": null, "tags": [] }
      ]
    }
  ],
  "presets": [
    { "id": "starter", "name": "Starter (recommended)",
      "description": "...",
      "categories": ["government","vendors","news"] }
  ]
}
```

### `POST /admin/seed-feeds`
Subscribe a user to the curated catalog.
```json
{ "username": "alice", "preset_id": "starter" }
```
Or:
```json
{ "username": "alice", "category_ids": ["government","news"] }
```
Returns:
```json
{
  "added_subscriptions": 18,
  "skipped_existing": 0,
  "new_feeds": 18,
  "by_category": { "government": 7, "vendors": 16, "news": 11 }
}
```

## Health

### `GET /healthz`
Public, unauthenticated:
```json
{ "ok": true, "name": "pharos", "version": "0.1.0" }
```
