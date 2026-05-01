# Pharos Documentation

> A beam through the noise.

| Topic | Description |
|---|---|
| [INSTALL.md](./INSTALL.md) | Step-by-step installation: scripted, manual, Docker (all-in-one and split), and bare-metal systemd. |
| [DEFAULT_FEEDS.md](./DEFAULT_FEEDS.md) | The curated feed catalog: government / vendors / news / research / Twitter (via Nitter/RSSHub). |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | High-level architecture, the three-stage pipeline, hot/cold storage, and constellation clustering. |
| [CONFIGURATION.md](./CONFIGURATION.md) | Every environment variable Pharos understands, with defaults and rationale. |
| [API.md](./API.md) | REST API reference: every route, request body, and response shape. |
| [SCHEMA.md](./SCHEMA.md) | SQLite schema reference for `hot.db` and `cold.db`. |
| [MITRE.md](./MITRE.md) | How Pharos integrates with MITRE ATT&CK Group / Software / Technique / Tactic IDs. |
| [LANTERN.md](./LANTERN.md) | The LLM enrichment engine: prompt, schema, fingerprint, and constellation algorithm. |
| [CLI.md](./CLI.md) | Every `pharos` CLI subcommand with examples. |
| [DEVELOPMENT.md](./DEVELOPMENT.md) | Local development workflow, tests, and code layout. |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Production deployment notes (backups, scaling, observability). |
| [FAQ.md](./FAQ.md) | Frequently asked questions and design rationale. |

## Quick links

- **Just want to run it?** Read [INSTALL.md](./INSTALL.md).
- **Want to understand the design?** Read [ARCHITECTURE.md](./ARCHITECTURE.md) then [LANTERN.md](./LANTERN.md).
- **Want to integrate with another tool?** Read [API.md](./API.md) and [SCHEMA.md](./SCHEMA.md).
- **Want to contribute?** Read [DEVELOPMENT.md](./DEVELOPMENT.md).
