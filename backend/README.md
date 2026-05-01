# pharos (backend)

This is the FastAPI backend for [Pharos](https://github.com/nullvaluefound/pharos),
a self-hosted, open-source AI-enabled news aggregator with LLM enrichment
and deterministic story clustering.

See the project root [README](https://github.com/nullvaluefound/pharos#readme)
for a full feature list, screenshots, and install instructions.

## Quick install

```bash
pip install -e ./backend
pharos init
pharos sweep   # ingestion loop
pharos light   # LLM enrichment loop
pharos notify  # watch checker
```

## Layout

- `pharos/api/`       — FastAPI routers and the application factory.
- `pharos/ingestion/` — RSS feed sweep + content extraction.
- `pharos/lantern/`   — LLM enrichment (the "Lantern").
- `pharos/notifier/`  — Watch checker that creates in-app notifications.
- `pharos/archive/`   — Hot → cold migration.
- `pharos/db/`        — SQLite schema + migration scripts.
- `pharos/cli.py`     — Typer-based CLI (`pharos ...`).

License: MIT.
