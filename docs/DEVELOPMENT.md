# Development Guide

## Repo layout

```
pharos/
  backend/
    pyproject.toml
    pharos/
      __init__.py
      config.py                  # pydantic-settings (env / .env)
      cli.py                     # `pharos` Typer app
      db/                        # SQLite schemas + connection helper
      ingestion/                 # Stage 1
      lantern/                   # Stage 2 (LLM + fingerprint + clusters)
      archiver/                  # Stage 3
      api/                       # FastAPI app + routes
    tests/
  frontend/                      # Next.js 14 reader UI
  deploy/
    docker/                      # Dockerfiles (aio, backend, frontend)
    compose/                     # docker-compose files
    systemd/                     # systemd units
  docs/                          # this folder
  install.ps1 / install.sh
  .env.example
  README.md
```

## Set up a dev environment

```bash
# clone
git clone <your fork>
cd pharos

# scripted dev install
./install.sh --frontend --dev          # or .\install.ps1 -WithFrontend -Dev

source .venv/bin/activate              # or .\.venv\Scripts\Activate.ps1
```

This installs the backend in editable mode with the `[dev]` extras
(`pytest`, `pytest-asyncio`, `ruff`, `respx`).

## Run the stack

In four terminals (all with the venv activated):

```bash
# 1. ingestion
pharos sweep

# 2. lantern (needs OPENAI_API_KEY)
pharos light

# 3. API
uvicorn pharos.api.app:create_app --factory --reload --port 8000

# 4. frontend
cd frontend && npm run dev
```

## Tests

```bash
cd backend
pytest -v
```

Test coverage today:

- `test_dedup.py` — URL canonicalization, SimHash similarity ordering.
- `test_parser.py` — RSS fixture parsing.
- `test_fingerprint_and_clusters.py` — fingerprint determinism,
  weighted Jaccard ordering, MITRE validation roundtrip.
- `test_mitre.py` — identifier validators and `attack.mitre.org` URL helper.
- `test_db_init_and_archiver.py` — init -> insert -> archive smoke
  test, including the `all_articles` UNION view.

Run with detailed logging:

```bash
pytest -v -o log_cli=true -o log_cli_level=DEBUG
```

## Code style

```bash
ruff check backend/pharos backend/tests
ruff format backend/pharos backend/tests
```

The project follows a few conventions:

- All SQL lives in `backend/pharos/db/*.sql` or as inline strings in
  the Python modules; we don't use an ORM.
- Database connections always go through
  [`pharos.db.connect()`](../backend/pharos/db/connection.py), which
  applies WAL + ATTACH cold + the `all_articles` view.
- Async-first for ingestion and the lantern; synchronous SQLite calls
  inside async functions are fine because each call is fast and we
  use a connection per logical operation.
- Each pipeline stage's `worker.py` / `scheduler.py` exposes
  `run_forever()` so the CLI can call it with `asyncio.run`.

## Adding a new pipeline stage

The pattern is consistent:

1. Add a new package under `backend/pharos/<stage_name>/`.
2. Add a `worker.py` (or `scheduler.py`) with `async def run_forever()`.
3. Read pending work from the DB; mark in-progress; do the work; persist;
   commit; sleep when idle.
4. Add a Typer subcommand in `backend/pharos/cli.py` that calls
   `asyncio.run(run_forever())`.
5. Add a systemd unit in `deploy/systemd/`.
6. Add a service entry in `deploy/compose/docker-compose.split.yml`
   and a `[program:...]` block in `deploy/docker/supervisord.conf`.

## Adding a new API route

1. Create a module under `backend/pharos/api/routes/`.
2. Define a `router = APIRouter(prefix=..., tags=[...])`.
3. Use `Depends(get_current_user)` (or `Depends(require_admin)`) for
   auth, `Depends(get_db)` for the SQLite connection.
4. Register it in [`pharos/api/app.py`](../backend/pharos/api/app.py).

## Adding fields to the LLM output

1. Edit [`pharos/lantern/schema.py`](../backend/pharos/lantern/schema.py)
   to add the new pydantic field (with validators where helpful).
2. Update [`pharos/lantern/prompts.py`](../backend/pharos/lantern/prompts.py)
   to instruct the model to populate it.
3. If it's a structured entity, update
   [`pharos/lantern/worker.py`](../backend/pharos/lantern/worker.py)
   `_persist_entities()` and the schema doc-comment in
   [`pharos/db/schema_hot.sql`](../backend/pharos/db/schema_hot.sql).
4. If it's high-signal for clustering, give it a namespace + weight in
   [`fingerprint.py`](../backend/pharos/lantern/fingerprint.py) and
   [`constellations.py`](../backend/pharos/lantern/constellations.py).
5. Add a unit test under `backend/tests/`.
6. Run `pharos reprocess` to regenerate against the new schema.

## Database changes

For now the schema is recreated idempotently from `schema_hot.sql` /
`schema_cold.sql`. When you add a column, add it as `ALTER TABLE ... ADD
COLUMN` inside a numbered `migrations/####.sql` file (the migrations
runner is not yet implemented; until then, document the change in
[CHANGELOG.md](./CHANGELOG.md)).

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend uses Next.js App Router + Tailwind. The `next.config.mjs`
proxies `/api/*` to `http://localhost:8000` for dev. In production
either set `PHAROS_API_URL` or run the frontend behind nginx (see the
deploy/systemd README).

API calls go through [`frontend/lib/api.ts`](../frontend/lib/api.ts)
which attaches the JWT and handles 401 redirects.

## Releasing

1. Bump the version in
   [`backend/pharos/__init__.py`](../backend/pharos/__init__.py) and
   [`backend/pyproject.toml`](../backend/pyproject.toml).
2. Run `pytest`.
3. Tag the commit (`git tag v0.x.0`).
4. Build images:
   ```bash
   docker build -t pharos/aio:0.x.0      -f deploy/docker/Dockerfile.aio .
   docker build -t pharos/api:0.x.0      -f deploy/docker/Dockerfile.backend .
   docker build -t pharos/frontend:0.x.0 -f deploy/docker/Dockerfile.frontend .
   ```
5. Push to your registry of choice.
