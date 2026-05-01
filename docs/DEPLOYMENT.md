# Deployment Notes

This document covers production concerns: backups, scaling, observability,
upgrades, and security. For *getting* Pharos running, see
[INSTALL.md](./INSTALL.md).

## Backups

Pharos's entire state is two SQLite files plus optional blobs:

```
$PHAROS_DB_DIR/
  hot.db       hot.db-wal       hot.db-shm
  cold.db      cold.db-wal      cold.db-shm
  blobs/       (optional raw HTML cache; expires automatically)
```

The recommended backup is the SQLite Online Backup API (safe while the
DB is open):

```bash
sqlite3 hot.db ".backup /backups/hot-$(date +%F).db"
sqlite3 cold.db ".backup /backups/cold-$(date +%F).db"
```

A daily cron job + offsite copy (S3/B2/Restic) is plenty. The cold DB
grows monotonically; the hot DB stays bounded by `ARCHIVE_AFTER_DAYS`.

To restore: stop all four workers, copy the backup files into
`$PHAROS_DB_DIR/`, restart.

## Scaling

Pharos is designed to run comfortably on a single VPS for a single user
or small team. Scale levers when you outgrow that:

| Bottleneck | Lever |
|---|---|
| LLM enrichment lag | Raise `LANTERN_CONCURRENCY` and `LANTERN_BATCH`; or run the lantern on a dedicated host (`pharos light` reads/writes the same SQLite over a shared volume; SQLite WAL handles concurrent readers, and the lantern is mostly write-heavy). |
| Stream API latency | Add an HTTP cache (varnish, nginx `proxy_cache`) in front. The stream endpoint is read-only and per-user. |
| SQLite write contention | The three writer stages (ingestion / lantern / archiver) write to disjoint table sets, but if you see `SQLITE_BUSY` errors raise `PRAGMA busy_timeout` (currently 5000ms in `connection.py`) or move the lantern to a separate process pool. |
| Disk usage | Lower `ARCHIVE_AFTER_DAYS` (more aggressive archive); `VACUUM` `cold.db` quarterly. |
| Number of users | Pharos was not designed for SaaS multi-tenancy; if you need that, deploy one instance per tenant. |

For very large feed counts (>1000 feeds), partition the scheduler by
running multiple `pharos sweep` instances each with a feed-id range
filter (not yet implemented; PRs welcome).

## Observability

- `GET /healthz` returns `{ "ok": true }` for liveness probes.
- `GET /api/v1/admin/pipeline` (admin) returns article counts by
  `enrichment_status`. Suitable for a Prometheus textfile collector;
  scrape it with a one-liner exporter.
- All workers log to stdout/stderr at the level set by `LOG_LEVEL`.
  Direct them to journald (systemd) or your container log driver.

Sample Prometheus textfile collector script:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -d '{"username":"prom","password":"..."}' \
  -H "Content-Type: application/json" | jq -r .access_token)

curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/admin/pipeline \
| jq -r '
    .counts_by_status | to_entries[] |
    "pharos_articles_total{status=\"\(.key)\"} \(.value)"
  ' > /var/lib/prometheus/node-exporter/pharos.prom
```

## Upgrades

```bash
git pull
source .venv/bin/activate
pip install -e ./backend
pharos init                    # idempotent; applies new schema bits

# restart workers
sudo systemctl restart pharos-api pharos-ingestion pharos-lantern
```

Prompt or schema changes that should be reflected in already-enriched
data:

```bash
pharos reprocess               # re-enrich failed/in_progress
# or, for everything:
sqlite3 $PHAROS_DB_DIR/hot.db "UPDATE articles SET enrichment_status='pending';"
```

## Security checklist

- [ ] `JWT_SECRET` is long, random, and not committed to git.
- [ ] `ALLOW_REGISTRATION=false` in production. Use `pharos adduser`.
- [ ] The API is behind HTTPS (nginx + Let's Encrypt; see
      [`deploy/systemd/README.md`](../deploy/systemd/README.md)).
- [ ] `OPENAI_API_KEY` is in `/etc/pharos/pharos.env` with `0640
      root:pharos` permissions.
- [ ] `CORS_ORIGINS` lists only the hosts that should be able to
      browser-call the API.
- [ ] The `pharos` system user is a service account with no shell.
- [ ] SQLite files (`$PHAROS_DB_DIR`) are owned by `pharos:pharos`
      with `0750`.
- [ ] Backups are encrypted at rest.

## Multi-host considerations

If you split workers across hosts, they must all see the same
`$PHAROS_DB_DIR`. SQLite over **NFS is not safe** for the WAL journal;
use a local filesystem on a single host, or one of:

- A small `tmpfs`-backed volume mounted into multiple containers on
  the same host (the [Docker split](./INSTALL.md#4-docker--split)
  layout).
- A SAN / iSCSI block device that supports `fcntl()` locks.

If you really need a network filesystem, you've outgrown SQLite — that's
the right time to consider a server DB.

## Cost

Operational cost is dominated by LLM API spend:

| Workload | Approx. cost (gpt-4o-mini, USD) |
|---|---|
| 1k articles / day | ~$0.15 / day |
| 10k articles / day | ~$1.50 / day |

Pharos calls the LLM exactly once per *new* article. Re-enrichment is
explicit (`pharos reprocess`).
