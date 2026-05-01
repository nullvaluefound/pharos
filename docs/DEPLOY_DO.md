# Deploying Pharos to the omnoptikon Digital Ocean droplet

This document describes how Pharos is deployed and — most importantly — **how
your `hot.db` and `cold.db` are kept safe across deploys**. Every Pharos
enrichment costs OpenAI tokens, so the deploy machinery is built around
"never lose the database" as a hard invariant.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  https://omnoptikon.com/                                        │
│                                                                 │
│        nginx (host)  ──>  127.0.0.1:3000   compose-frontend-1   │
│                            (Vite SPA + nginx)                   │
│                                  │                              │
│                                  │  /api/* (kept as /api/*)     │
│                                  ▼                              │
│                            127.0.0.1:8000   compose-pharos-1    │
│                            (FastAPI + sweep + lantern +         │
│                             notifier + archiver via             │
│                             supervisord)                        │
│                                  │                              │
│                                  ▼                              │
│                            volume: compose_pharos_data          │
│                            ├── hot.db    (active)               │
│                            ├── cold.db   (archive)              │
│                            └── blobs/                           │
│                                                                 │
│  Snapshots: /opt/pharos/backups/docker-volume-<ts>.tgz          │
│  (last 10 kept; one taken before every deploy)                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Database safety guarantees

Pharos's deploy script (`scripts/deploy_do.py`) makes the following
guarantees, in order:

1. **The DB volume is `external: true` in `docker-compose.aio.yml`.**
   `docker compose down -v` will not remove it. `docker compose up` cannot
   accidentally recreate it as empty by being run from a different
   directory (which would have changed the implicit project name).

2. **Every deploy starts with a tarball snapshot of the live volume.**
   The snapshot is written to `/opt/pharos/backups/docker-volume-<ts>.tgz`
   on the droplet *before* any `docker compose build` or `up` is run. We
   keep the most recent 10 snapshots automatically.

3. **Pre-flight refuses to deploy on top of an empty volume.** If the
   script sees an unexpectedly small `hot.db` (< 1KB), it bails out with a
   non-zero exit code rather than risk pretending an empty DB is the
   correct state. Pass `--first-time` if you really do mean to deploy a
   fresh droplet.

4. **`*.db`, `*.db-wal` and `*.db-shm` files are excluded from the SFTP
   source upload.** Even if a stray DB file ends up in your local working
   tree, it cannot overwrite the live DB on the droplet through a code
   sync.

5. **Post-deploy verification refuses to declare success on data loss.**
   The script records `users` / `articles` / `enriched` counts before
   deploying and checks them again afterwards. Any decrease aborts with
   exit code 6 and prints the exact restore command for the snapshot it
   took five minutes earlier.

6. **One-command rollback.** Every successful run prints:

   ```
   Restore: python scripts/deploy_do.py --restore /opt/pharos/backups/<file>.tgz
   ```

   That command stops the stack, wipes the volume, untars the snapshot
   back into place, and brings the stack up again.

## Deploy commands

All commands run from your workstation. They use SSH/SFTP via paramiko, so
the only local prereq is `pip install paramiko`.

```bash
# Standard deploy: snapshot, sync source, build all images, recreate, verify
python scripts/deploy_do.py

# Frontend only (much faster). Backend left untouched.
python scripts/deploy_do.py --frontend-only

# Backend only.
python scripts/deploy_do.py --backend-only

# Reuse the source/images already on the droplet (just bounce containers)
python scripts/deploy_do.py --no-source --no-build

# Brand-new droplet (creates the volume; never overwrites an existing one)
python scripts/deploy_do.py --first-time

# Roll back to a specific snapshot (DESTRUCTIVE — overwrites current DB)
python scripts/deploy_do.py --restore /opt/pharos/backups/docker-volume-<ts>.tgz
```

## Operational commands (run on the droplet)

```bash
# Live logs
docker logs -f --tail 50 compose-pharos-1
docker logs -f --tail 50 compose-frontend-1

# Restart just the API (e.g. after .env edits)
docker compose -f /opt/pharos/deploy/compose/docker-compose.aio.yml \
  restart pharos

# Show DB metrics (uses the deploy_do.py inspector)
docker run --rm -v compose_pharos_data:/data:ro python:3.12-slim \
  python -c "import sqlite3; \
    db=sqlite3.connect('file:/data/hot.db?immutable=1', uri=True); \
    print('users:',    db.execute('select count(*) from users').fetchone()[0]); \
    print('articles:', db.execute('select count(*) from articles').fetchone()[0]); \
    print('enriched:', db.execute('select count(*) from articles where overview is not null').fetchone()[0])"

# List snapshots
ls -lh /opt/pharos/backups/

# Manual snapshot
docker run --rm -v compose_pharos_data:/data:ro \
  -v /opt/pharos/backups:/backup alpine:3.20 \
  sh -c "tar -C /data -czf /backup/manual-$(date +%Y%m%d-%H%M%S).tgz ."

# Pull a snapshot down to your workstation
python scripts/db_pull_remote.py
```

## Manual restore from a snapshot

```bash
# 1. Stop the stack so nothing is mid-write
cd /opt/pharos/deploy/compose
docker compose -f docker-compose.aio.yml stop pharos

# 2. Replace the volume contents from a snapshot
docker run --rm -v compose_pharos_data:/data \
  -v /opt/pharos/backups:/backup:ro alpine:3.20 \
  sh -c 'rm -rf /data/* /data/.[!.]*; \
         tar -xzf /backup/<snapshot>.tgz -C /data && ls -la /data'

# 3. Start the stack again
docker compose -f docker-compose.aio.yml up -d
```

Or, equivalently:

```bash
python scripts/deploy_do.py --restore /opt/pharos/backups/<snapshot>.tgz
```

## Why the deploy script is paramiko-based instead of plain SSH

To match the pattern used by the other apps on the same droplet
(`reddit-copilot`, `threat-actor-attribution`, `openprism-relay`). It
also lets us:

* Read structured exit codes from each remote step
* Strip CRLF from text files before SFTP-uploading them so bash on the
  droplet doesn't fail with "/bin/sh\r: not found"
* Run the live-volume inspection in-process via `docker run` against the
  named volume, regardless of whether the pharos container is up
