# Installation Guide

Pharos can be installed four ways. Pick the one that matches your environment:

| Mode | Best for | Section |
|---|---|---|
| Scripted | Local development, single-machine self-hosting | [Scripted](#1-scripted-recommended-for-most-users) |
| Manual | Custom Python setups, troubleshooting | [Manual](#2-manual) |
| Docker (all-in-one) | One small VPS / NAS | [Docker AIO](#3-docker--all-in-one) |
| Docker (split) | A dedicated host where you want stages separated | [Docker Split](#4-docker--split) |
| Bare metal + systemd | Production Linux servers | [systemd](#5-bare-metal--systemd) |

## Prerequisites

- **All modes**:
  - An OpenAI API key (or another OpenAI-compatible endpoint) — required for the lantern.
  - At least 1 GB of free disk space for the SQLite databases (more if you keep many feeds for a long time).
- **Scripted / Manual / systemd**:
  - Python 3.11 or newer.
  - Node.js 20+ if you want to run the frontend.
- **Docker modes**:
  - Docker 24+ and Docker Compose v2.

## 1. Scripted (recommended for most users)

The repository ships with cross-platform install scripts that:

1. Create a Python virtualenv at `.venv`.
2. Install the Pharos backend (and optionally the `[dev]` extras).
3. **Run [`setup-env.sh`](../setup-env.sh) / [`setup-env.ps1`](../setup-env.ps1)** to:
   - Auto-generate a strong `JWT_SECRET` (so you don't ship a placeholder secret).
   - **Prompt** you for `OPENAI_API_KEY` (Enter to skip and set later).
   - Offer to override `OPENAI_MODEL` and `PHAROS_DB_DIR`.
4. Initialize the SQLite databases (`pharos init`).
5. **Prompt** you to create an admin user.
6. Optionally install the frontend.

Pass `--non-interactive` (POSIX) or `-NonInteractive` (PowerShell) to skip
all prompts (useful in CI). In that mode the API key is *not* prompted and
will remain the placeholder until you edit `.env`.

### Windows (PowerShell)

```powershell
git clone https://github.com/your-org/pharos.git
cd pharos
.\install.ps1 -WithFrontend -Dev
```

If PowerShell refuses to run unsigned scripts, allow them for the current
session first:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### Linux / macOS

```bash
git clone https://github.com/your-org/pharos.git
cd pharos
chmod +x install.sh
./install.sh --frontend --dev
```

### After scripted install

The script already configured `.env`, optionally created your first
user, and offered to subscribe that user to one of the curated **feed
presets** (see [DEFAULT_FEEDS.md](./DEFAULT_FEEDS.md)). So:

1. Activate the virtualenv:
   - Windows: `.\.venv\Scripts\Activate.ps1`
   - Linux/macOS: `source .venv/bin/activate`
2. (Optional) Subscribe to more feeds: `pharos seed-feeds -u alice -p full`
   or `pharos watch <url> -u alice`
3. Run the workers (each in its own terminal):
   - `pharos sweep` — the ingestion scheduler (Stage 1)
   - `pharos light` — the lantern / LLM enrichment (Stage 2)
4. Run the API: `uvicorn pharos.api.app:create_app --factory --port 8000`
5. (Optional) Run the frontend: `cd frontend && npm run dev`

Open <http://localhost:3000> and sign in.

### Reconfiguring later

You can re-run the env bootstrapper at any time without reinstalling:

```bash
./setup-env.sh           # interactive
./setup-env.sh --no-prompt
```

It only edits `.env`; it never touches the venv or the databases.

## 2. Manual

If you would rather run each command yourself:

```bash
# 1. clone + venv
git clone https://github.com/your-org/pharos.git
cd pharos
python -m venv .venv
source .venv/bin/activate          # or .venv\Scripts\Activate.ps1 on Windows

# 2. install backend
pip install --upgrade pip wheel
pip install -e ./backend[dev]

# 3. configuration
cp .env.example .env
$EDITOR .env                        # set OPENAI_API_KEY + JWT_SECRET

# 4. initialize SQLite databases
pharos init

# 5. create a user, subscribe to a feed
pharos adduser alice --admin
pharos watch https://feeds.feedburner.com/TheHackersNews -u alice

# 6. run the pipeline (separate terminals)
pharos sweep
pharos light
uvicorn pharos.api.app:create_app --factory --port 8000

# 7. (optional) frontend
cd frontend
npm install
npm run dev
```

## 3. Docker — all-in-one

One container runs the API + scheduler + lantern + archiver under
`supervisord`. A second container runs the Next.js frontend. A tiny
`preflight` container runs first and **refuses to let the stack start
if `.env` still has placeholder values**.

```bash
git clone https://github.com/your-org/pharos.git
cd pharos

# 1. Bootstrap .env interactively (auto-generates JWT_SECRET, prompts for API key).
./setup-env.sh                              # or .\setup-env.ps1 on Windows

# 2. Bring it up.
docker compose -f deploy/compose/docker-compose.aio.yml up -d --build
```

If you skip step 1, the `preflight` container exits non-zero and the
main containers won't start. The error message tells you exactly what
to do.

Then create your user inside the container:

```bash
docker compose -f deploy/compose/docker-compose.aio.yml exec pharos \
  pharos adduser alice --admin

docker compose -f deploy/compose/docker-compose.aio.yml exec pharos \
  pharos watch https://feeds.feedburner.com/TheHackersNews -u alice
```

- API: <http://localhost:8000/docs>
- UI: <http://localhost:3000>

## 4. Docker — split

Each pipeline stage runs in its own container, all sharing the same SQLite volume.
SQLite WAL mode permits many concurrent readers; each writer (ingestion / lantern /
archiver) operates on a logically distinct slice of the schema, so contention is
minimal. Same `preflight` guard as the AIO mode.

```bash
./setup-env.sh                              # or .\setup-env.ps1 on Windows
docker compose -f deploy/compose/docker-compose.split.yml up -d --build
docker compose -f deploy/compose/docker-compose.split.yml exec api \
  pharos adduser alice --admin
```

Containers spawned: `api`, `ingestion`, `lantern`, `archiver`, `frontend`.

## 5. Bare metal + systemd

For long-running production deployments on a Linux host. Full instructions
live in [`deploy/systemd/README.md`](../deploy/systemd/README.md), summarized:

```bash
# 1. user + dirs
sudo useradd -r -s /usr/sbin/nologin pharos
sudo mkdir -p /opt/pharos /etc/pharos /var/lib/pharos
sudo chown -R pharos:pharos /opt/pharos /var/lib/pharos

# 2. install into a system venv
sudo -u pharos python3 -m venv /opt/pharos/venv
sudo -u pharos /opt/pharos/venv/bin/pip install /path/to/pharos/backend

# 3. configuration (set PHAROS_DB_DIR=/var/lib/pharos)
sudo cp .env.example /etc/pharos/pharos.env
sudo $EDITOR /etc/pharos/pharos.env

# 4. databases + first user
sudo -u pharos /opt/pharos/venv/bin/pharos init
sudo -u pharos /opt/pharos/venv/bin/pharos adduser admin --admin

# 5. systemd units
sudo cp deploy/systemd/pharos-*.service deploy/systemd/pharos-*.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
  pharos-api.service pharos-ingestion.service \
  pharos-lantern.service pharos-archiver.timer
```

A reverse-proxy snippet for nginx is provided in the same README.

## Verifying the install

After any install method, you can sanity-check the pipeline:

```bash
pharos status            # article counts by enrichment_status
pharos feeds             # subscribed feeds + last-poll status
curl http://localhost:8000/healthz
```

The first time you run `pharos light`, watch the logs — you should see
`enriched article N (...)` lines as the LLM finishes each article. Once at
least two feeds cover the same story, you'll see those articles share a
`story_cluster_id` (a "constellation").

## Upgrading

```bash
git pull
source .venv/bin/activate
pip install -e ./backend
pharos init                   # idempotent; applies any new schema migrations
```

For Docker:

```bash
git pull
docker compose -f deploy/compose/docker-compose.aio.yml up -d --build
```

## Uninstalling

```bash
# stop everything first
deactivate
rm -rf .venv data .env

# Docker
docker compose -f deploy/compose/docker-compose.aio.yml down -v

# systemd
sudo systemctl disable --now pharos-*.service pharos-*.timer
sudo rm /etc/systemd/system/pharos-*.{service,timer}
sudo rm -rf /opt/pharos /etc/pharos /var/lib/pharos
sudo userdel pharos
```

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `OPENAI_API_KEY is not set` in lantern logs | `.env` not loaded or empty | Check that `.env` is in the working directory of the lantern process. |
| Articles stuck in `pending` | Lantern worker not running | Run `pharos light`. Check `pharos status`. |
| All feeds show `error_count > 0` | Network or User-Agent blocking | Check `last_status`; try `HTTP_USER_AGENT` in `.env`. |
| 401 from the UI | Token expired | Sign out and back in. |
| Frontend can't reach API | CORS or rewrite issue | Set `CORS_ORIGINS=http://localhost:3000` and restart the API. |
