# Default Feeds

Pharos ships with a curated catalog of feeds so a brand-new install has
useful content from the moment you run `pharos sweep` and `pharos light`.

The catalog lives at
[`backend/pharos/data/default_feeds.yaml`](../backend/pharos/data/default_feeds.yaml)
and is bundled with the Python wheel. Edit it to add or remove feeds for
your installation; PRs to update the upstream list are welcome.

## Categories

| ID | Name | Default | Description |
|---|---|---|---|
| `government` | Government & CERTs | yes | Authoritative advisories from CISA, NCSC UK, CERT-EU, ACSC, NVD. |
| `vendors` | Security Vendors | yes | Threat-intel research blogs from Microsoft, Google/Mandiant, CrowdStrike, Talos, Unit 42, SentinelLabs, Sophos, ESET, Trend Micro, Kaspersky, Recorded Future, Volexity, Check Point, Proofpoint. |
| `news` | Security News | yes | BleepingComputer, The Hacker News, KrebsOnSecurity, Dark Reading, SecurityWeek, The Register, Wired, Ars Technica, CyberScoop, The Record, InfoSecurity Magazine. |
| `research` | Research & Independent | yes | Project Zero, Citizen Lab, Schneier, Troy Hunt, Tavis Ormandy, GreyNoise. |
| `twitter` | Twitter / X (bridge) | **no** | Templates for Nitter / RSSHub. **You must edit before use.** See [below](#twitter--x). |

## Presets

| ID | Includes |
|---|---|
| `starter` | `government`, `vendors`, `news` |
| `minimal` | `government` only |
| `full` | `government`, `vendors`, `news`, `research` |
| `everything` | All five categories (Twitter included; will fail until you edit URLs). |

## Subscribing a user

The install scripts will offer to do this automatically. To do it
manually:

```bash
# show the catalog
pharos catalog

# preview without writing
pharos seed-feeds -u alice --list

# subscribe to the recommended starter set
pharos seed-feeds -u alice -p starter

# pick specific categories
pharos seed-feeds -u alice -c government,news

# add everything (incl. Twitter templates)
pharos seed-feeds -u alice -p everything
```

`pharos seed-feeds` is idempotent — re-running it just skips
subscriptions you already have.

The same operation is available over HTTP for admins:

```bash
curl -X POST http://localhost:8000/api/v1/admin/seed-feeds \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","preset_id":"starter"}'

# or list the catalog
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/feed-catalog
```

## Customizing the catalog

The YAML file is the source of truth. Each entry supports:

```yaml
- title: "Friendly name (optional)"
  url:   "https://example.com/feed.xml"          # required
  folder: "Vendors"                              # optional, overrides category folder
  poll_interval_sec: 600                         # optional, overrides default cadence
  tags: ["incident-response", "ransomware"]     # optional, free-text tags
```

To add your own permanent additions:

1. Edit `backend/pharos/data/default_feeds.yaml`.
2. Reinstall (`pip install -e ./backend`) or rebuild the Docker image.
3. Re-run `pharos seed-feeds` — already-existing subscriptions are
   skipped, new ones are added.

## Twitter / X

X discontinued public RSS in 2023. Pharos treats X feeds the same as any
other feed — it just needs an RSS URL. Three ways to get one:

### Option A — Nitter (community mirrors, free, fragile)

[Nitter](https://github.com/zedeus/nitter) is an alternative Twitter
front-end that exposes RSS at `https://<instance>/<handle>/rss`. Public
instances come and go; check
[zedeus/nitter#wiki/Instances](https://github.com/zedeus/nitter/wiki/Instances)
or the community-maintained [status page](https://status.d420.de/) for a
currently-working host. Two reasonably-stable ones at the time of
writing:

- `https://nitter.privacydev.net/<handle>/rss`
- `https://nitter.poast.org/<handle>/rss`

Then in `default_feeds.yaml` (or via `pharos watch`):

```bash
pharos watch https://nitter.privacydev.net/CISAgov/rss -u alice --folder Twitter
```

### Option B — RSSHub (self-hosted, reliable)

[RSSHub](https://docs.rsshub.app/) is a Node.js service that produces
RSS for hundreds of sources, X included. Run it on your own machine and
your URLs become stable:

```yaml
url: "https://your-rsshub.example.com/twitter/user/CISAgov"
```

Docker quickstart:

```bash
docker run -d --name rsshub -p 1200:1200 diygod/rsshub
```

Then `https://localhost:1200/twitter/user/<handle>` is your URL pattern.
Note that X has been increasingly hostile to scrapers; RSSHub may need
authenticated cookies to keep working.

### Option C — Wait for a Pharos X connector

A first-class X-API connector is on the roadmap (it would not be a
generic feed; instead Pharos would call X's `GET /2/users/by/username`
+ tweet timeline endpoints directly). Track issues for progress.

### Updating the bundled Twitter examples

The `twitter` category in `default_feeds.yaml` uses
`YOUR_NITTER_OR_RSSHUB` as a placeholder host. Replace it with a URL
template that works for you, then run:

```bash
pharos seed-feeds -u alice -c twitter
```

If you have not edited the placeholders, the lantern will simply log
fetch errors against those feeds (you'll see them in `pharos feeds`
with `error_count > 0`). Remove them with `pharos` UI or:

```bash
sqlite3 data/hot.db "DELETE FROM feeds WHERE url LIKE '%YOUR_NITTER_OR_RSSHUB%';"
```

## Cost considerations

Each feed adds enrichment cost (one LLM call per new article). With the
default `starter` preset (~30 feeds) you should expect:

- ~50–150 new articles per day (the news category dominates).
- ~$0.05–$0.20/day on `gpt-4o-mini`.
- Hot DB stays well under 1 GB even after a year.

If you want to keep cost minimal, use the `minimal` preset (CISA only,
~5 feeds, <10 articles/day).
