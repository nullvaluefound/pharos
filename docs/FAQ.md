# FAQ

## Why SQLite?

Because Pharos targets individuals and small teams self-hosting on
modest hardware, not SaaS scale. SQLite gives us:

- A single-file backup story (`cp hot.db backup/`).
- FTS5 for text search.
- Built-in WAL for concurrent reads.
- Zero ops.

If you ever need a server DB, the schema in
[SCHEMA.md](./SCHEMA.md) maps directly onto Postgres without changes
beyond `INTEGER PRIMARY KEY AUTOINCREMENT` -> `BIGSERIAL`.

## Why an LLM instead of an NLP pipeline?

A traditional newsroom-grade enrichment stack is a multi-year ML pipeline
(NER models, topic classifiers, deduplicators, etc.). For a self-hosted
deployment aimed at one user or a small team, that's overkill — and you'd
need to host and maintain models. An LLM with a strict JSON schema:

- Replaces the entire NER + topic + summarization stack with one HTTP
  call per article.
- Costs <$2/day even at 10k articles/day on `gpt-4o-mini`.
- Is replaceable: any OpenAI-compatible endpoint works (Ollama,
  vLLM, llama.cpp via `OPENAI_BASE_URL`).

## Why deterministic clustering instead of embeddings?

Three reasons:

1. **Explainability.** The `/related` endpoint returns the exact
   `shared_tokens` that drove the score. The user can see why two
   articles were grouped.
2. **No extra infrastructure.** Embeddings imply a vector DB. Pharos
   stays SQLite-only.
3. **Quality is high because the LLM did the semantic work upstream.**
   The fingerprint includes MITRE Group / Software / Technique IDs,
   which are unambiguous global identifiers — token overlap on these
   is *better* than embedding cosine similarity for security articles.

If you want fuzzy semantic similarity later, drop in
[`sqlite-vec`](https://github.com/asg017/sqlite-vec) and add a vector
namespace to the fingerprint without touching the rest of the design.

## Will I get rate-limited by feed publishers?

Pharos sends `If-None-Match` / `If-Modified-Since` headers, so a
well-implemented feed returns `304 Not Modified` for unchanged content
(no body transferred). Per-feed `poll_interval_sec` defaults to 15
minutes; raise it for low-update sources.

Set `HTTP_USER_AGENT` to include a contact URL — many publishers
specifically allow well-identified bots.

## What feeds does Pharos start with?

A curated catalog covering five categories: government CERTs (CISA,
NCSC, CERT-EU, ACSC, NVD), security-vendor research blogs (Microsoft,
Google/Mandiant, CrowdStrike, Talos, Unit 42, SentinelLabs, Sophos,
ESET, Trend Micro, Kaspersky, Recorded Future, Volexity, Check Point,
Proofpoint), security news (BleepingComputer, The Hacker News,
KrebsOnSecurity, Dark Reading, SecurityWeek, The Register, Wired, Ars
Technica, CyberScoop, The Record, InfoSecurity), independent research
(Project Zero, Citizen Lab, Schneier, Troy Hunt, Tavis Ormandy,
GreyNoise), and Twitter/X (via Nitter or RSSHub bridges — these
require editing a placeholder URL before they work).

The install script offers to subscribe you to a preset; you can also
run `pharos seed-feeds -u <user> -p starter` at any time. Full list and
customization in [DEFAULT_FEEDS.md](./DEFAULT_FEEDS.md).

## Can I follow accounts on Twitter/X?

Yes, but X has no public RSS so you need a bridge:

1. **Nitter** — community-run mirror, free, fragile. Pattern:
   `https://<instance>/<handle>/rss`. Public instances die often; check
   the [Nitter wiki](https://github.com/zedeus/nitter/wiki/Instances).
2. **RSSHub** — self-hostable, reliable. Pattern:
   `https://<your-rsshub>/twitter/user/<handle>`.
3. A first-class X-API connector is on the roadmap.

The `twitter` category in the bundled catalog provides templates with a
`YOUR_NITTER_OR_RSSHUB` placeholder you must replace. See
[DEFAULT_FEEDS.md#twitter--x](./DEFAULT_FEEDS.md#twitter--x).

## How do I import an OPML file from another reader?

Not yet implemented in the UI — for now use the CLI with a tiny script:

```bash
python -c '
import xml.etree.ElementTree as ET, subprocess, sys
tree = ET.parse(sys.argv[1])
for outline in tree.iter("outline"):
    url = outline.attrib.get("xmlUrl")
    if url:
        subprocess.run(["pharos","watch", url, "-u", "alice"])
' subscriptions.opml
```

A real `pharos opml-import` / `pharos opml-export` is on the roadmap.

## Can I use a local LLM (Ollama / llama.cpp)?

Yes — set `OPENAI_BASE_URL` to your local OpenAI-compatible endpoint
and `OPENAI_MODEL` to whatever model identifier it expects. The model
must support OpenAI's `response_format=json_schema` Chat Completions
extension. As of mid-2026 that includes most modern open models served
via vLLM, llama.cpp's `--json-schema`, and Ollama's structured outputs.

If your local model can't do strict JSON schema enforcement, expect a
higher rate of validation failures. They land in `enrichment_status='failed'`
with the error in `enrichment_error`; `pharos reprocess --failed-only`
retries them.

## How do I migrate from another reader?

| Source | How |
|---|---|
| Most hosted readers | Export OPML from the reader's Settings / Organize / Import-Export menu, then run the import script above. |
| Inoreader | Settings -> Preferences -> Import/Export -> Export OPML. |
| Miniflux | `miniflux export-opml` -> import. |
| TT-RSS | Plugin or `feed_export` CLI -> import. |

## Can multiple users share a constellation?

Yes. Articles, entities, and constellations are global; only
subscriptions, read/saved state, and watches are per-user. Two users
subscribed to overlapping feeds see the same constellations in their
streams (filtered to their own subscriptions).

## How is my data isolated between users?

Per-user state lives in `user_article_state` and `saved_searches`,
both keyed by `user_id`. Every API endpoint scopes its queries to the
authenticated user. Articles, feeds, entities, and constellations are
shared so that the LLM enrichment cost is paid once per article, not
per user.

If you need strict tenant isolation (no shared articles), run one
Pharos instance per tenant.

## What's NOT implemented yet?

- OPML import/export UI (CLI workaround above).
- WebSub / PubSubHubbub push subscriptions (we only poll).
- A graphical filter builder (the watches page accepts raw JSON).
- Notifications when a watch fires (the `notify` flag is stored but
  not yet acted on).
- Semantic search via `sqlite-vec`.
- Per-feed adaptive polling (we use a fixed default + manual override).
- Multi-host SQLite replication (intentionally — see
  [DEPLOYMENT.md](./DEPLOYMENT.md)).

PRs welcome on any of the above.
