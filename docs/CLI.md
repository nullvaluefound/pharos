# CLI Reference

The `pharos` command is installed by `pip install ./backend` (or by the
install script). Greek-flavored verbs cover the worker stages
(`sweep` / `light` / `archive`) and friendly verbs cover management
(`init` / `adduser` / `watch` / `feeds` / `status` / `reprocess`).

Run any command with `--help` for inline help, e.g. `pharos light --help`.

## `pharos init`

Creates `hot.db` and `cold.db` (with WAL, FTS5, and the full schema).
Idempotent: safe to re-run after upgrading.

```bash
pharos init
```

## `pharos adduser <username> [--admin]`

Creates a local user. Prompts twice for the password. Admin users have
access to `/admin/*` endpoints.

```bash
pharos adduser alice --admin
```

## `pharos watch <feed-url> --user <name> [--folder <name>]`

Subscribes a user to a feed. Creates the feed if Pharos hasn't seen it
before; otherwise just adds the subscription row.

```bash
pharos watch https://feeds.feedburner.com/TheHackersNews -u alice
pharos watch https://example.com/feed.xml -u alice --folder Security
```

## `pharos catalog`

Print the bundled curated feed catalog (categories + presets). See
[DEFAULT_FEEDS.md](./DEFAULT_FEEDS.md) for the full list and rationale.

```bash
pharos catalog
```

## `pharos seed-feeds --user <name> [--preset P | --categories C,...] [--list]`

Bulk-subscribes a user to the curated catalog. Idempotent — already-subscribed
feeds are skipped.

```bash
# the recommended starter set: government + vendors + news
pharos seed-feeds -u alice -p starter

# pick categories explicitly
pharos seed-feeds -u alice -c government,research

# preview without writing
pharos seed-feeds -u alice -p everything --list

# CISA only
pharos seed-feeds -u alice -p minimal
```

## `pharos feeds`

Tabular view of every feed Pharos knows about and its poll status.

```bash
pharos feeds
```

## `pharos status`

Counts of articles by `enrichment_status` plus the cold-DB total. Use
this to confirm the lantern is keeping up.

```bash
pharos status
```

Example output:
```
        Pharos Pipeline
+-------------------+--------+
| status            |  count |
+-------------------+--------+
| pending           |     12 |
| in_progress       |      4 |
| enriched          |   3982 |
| failed            |      3 |
| archived (cold)   |  12450 |
+-------------------+--------+
```

## `pharos sweep`

**Stage 1: ingestion scheduler.** Runs in the foreground, polling each
feed at its configured cadence. Use `Ctrl-C` to stop.

```bash
pharos sweep
```

In production, run this under systemd (`pharos-ingestion.service`) or
a process manager.

## `pharos light`

**Stage 2: the lantern (LLM enrichment).** Runs in the foreground,
claiming pending articles and producing `EnrichedArticle` records.
Use `Ctrl-C` to stop.

```bash
pharos light
```

Tunable via `LANTERN_BATCH`, `LANTERN_CONCURRENCY`,
`LANTERN_POLL_INTERVAL_SEC` in `.env`.

## `pharos archive`

**Stage 3: the archiver.** One-shot. Moves articles older than
`ARCHIVE_AFTER_DAYS` from hot to cold and drops the raw HTML.

```bash
pharos archive
```

Run this nightly via cron, systemd timer, or the `archiver` container
in compose. The CLI command runs exactly one pass and exits.

## `pharos reprocess [--failed-only] [--id N]`

Resets `enrichment_status` to `pending` so the lantern re-enriches the
matching rows. Useful after:

- A prompt or schema change (re-enrich everything).
- A run of failures (`--failed-only`).
- Targeted debugging (`--id 1234 --id 5678`).

```bash
pharos reprocess --failed-only
pharos reprocess --id 1234 --id 5678
pharos reprocess          # resets failed + in_progress (NOT 'enriched')
```

To re-enrich `enriched` rows too (e.g. after a prompt overhaul):

```bash
sqlite3 data/hot.db "UPDATE articles SET enrichment_status='pending';"
```

## Running the API

The API is a separate command (not currently bundled into the `pharos`
CLI):

```bash
uvicorn pharos.api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Add `--reload` for development.
