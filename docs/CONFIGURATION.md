# Configuration

Pharos reads configuration from environment variables (and from a `.env`
file in the working directory, courtesy of `pydantic-settings`).

The canonical example is [`.env.example`](../.env.example). Every
variable below is optional unless marked **required**.

## Required

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | API key used by the lantern. Without it, enrichment cannot run. |
| `JWT_SECRET` | Secret used to sign session tokens. **Must be a long random string in production.** |

Generate a secret on the fly:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## LLM

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name. Must support `response_format=json_schema`. |
| `OPENAI_BASE_URL` | (unset) | Override the OpenAI endpoint. Set this to talk to an OpenAI-compatible local server (vLLM, llama-server, etc.). |

## Storage

| Variable | Default | Purpose |
|---|---|---|
| `PHAROS_DB_DIR` | `./data` | Directory where `hot.db`, `cold.db`, and `blobs/` live. |

The hot DB and cold DB paths are derived from this directory.

## Retention (archiver)

| Variable | Default | Purpose |
|---|---|---|
| `ARCHIVE_AFTER_DAYS` | `45` | Articles older than this (and already enriched/failed) move to `cold.db`. |

## Constellations (cross-source clustering)

These tune the deterministic story-clustering algorithm. See
[LANTERN.md](./LANTERN.md) for the math.

| Variable | Default | Purpose |
|---|---|---|
| `CLUSTER_WINDOW_DAYS` | `7` | Only consider candidate articles within this many days. |
| `CLUSTER_MIN_SHARED` | `4` | A candidate must share at least this many tokens to be scored. |
| `CLUSTER_SIM_THRESHOLD` | `0.55` | Minimum weighted Jaccard similarity to attach to an existing cluster. |

If the same story is fragmenting into too many small clusters, *lower*
`CLUSTER_SIM_THRESHOLD` (e.g. `0.45`). If unrelated stories are merging,
*raise* it (e.g. `0.65`).

## Lantern (enrichment worker)

| Variable | Default | Purpose |
|---|---|---|
| `LANTERN_BATCH` | `10` | How many pending rows to claim at a time. |
| `LANTERN_CONCURRENCY` | `4` | How many LLM calls to keep in flight in parallel. |
| `LANTERN_POLL_INTERVAL_SEC` | `10` | Seconds to sleep when there's no work. |

Throughput tip: with `gpt-4o-mini`, `LANTERN_CONCURRENCY=8` and
`LANTERN_BATCH=20` is comfortably within most rate limits and gets you
~30 articles/minute.

## Ingestion (scheduler / fetcher)

| Variable | Default | Purpose |
|---|---|---|
| `DEFAULT_FEED_POLL_INTERVAL_SEC` | `900` | How often to poll a newly-added feed (15 min). |
| `HTTP_USER_AGENT` | `Pharos/0.1` | Sent on every outbound HTTP request. Some sites block default UAs; include a contact URL. |

Per-feed `poll_interval_sec` lives in the `feeds` table and can be
edited directly with SQL or via the admin UI (when added).

## API

| Variable | Default | Purpose |
|---|---|---|
| `JWT_ALGORITHM` | `HS256` | Signing algorithm for session tokens. |
| `JWT_TTL_SECONDS` | `604800` (7 days) | Session token lifetime. |
| `ALLOW_REGISTRATION` | `false` | If `true`, `POST /auth/register` is open. Otherwise users must be created via `pharos adduser`. |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated list of allowed origins. |

## Logging

| Variable | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Standard Python log level. Use `DEBUG` while diagnosing pipeline issues. |

## A complete `.env` for production

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
JWT_SECRET=<long random string>
JWT_TTL_SECONDS=2592000

PHAROS_DB_DIR=/var/lib/pharos
ARCHIVE_AFTER_DAYS=60

CLUSTER_WINDOW_DAYS=10
CLUSTER_MIN_SHARED=4
CLUSTER_SIM_THRESHOLD=0.55

LANTERN_BATCH=20
LANTERN_CONCURRENCY=8
LANTERN_POLL_INTERVAL_SEC=5

DEFAULT_FEED_POLL_INTERVAL_SEC=900
HTTP_USER_AGENT=Pharos/0.1 (+https://your.host/contact)

ALLOW_REGISTRATION=false
CORS_ORIGINS=https://pharos.your.host
LOG_LEVEL=INFO
```
