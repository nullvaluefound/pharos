# The Lantern (Stage 2 — Enrichment Engine)

The lantern is the heart of Pharos. It turns raw article text (handed
over by Stage 1 ingestion) into a structured `EnrichedArticle` JSON
record, then assigns the article to a "constellation" so cross-source
coverage of the same story collapses into one stream item.

The whole pipeline is **deterministic and explainable** outside the LLM
call itself: the prompt is fixed, the JSON schema is enforced, the
fingerprint algorithm is pure, and the clusterer's weights live in
config.

## Files

| File | Purpose |
|---|---|
| [`schema.py`](../backend/pharos/lantern/schema.py) | `EnrichedArticle` pydantic model. The contract. |
| [`mitre.py`](../backend/pharos/lantern/mitre.py) | MITRE ATT&CK ID validation + canonical URLs. |
| [`prompts.py`](../backend/pharos/lantern/prompts.py) | System and user prompt templates. |
| [`llm_client.py`](../backend/pharos/lantern/llm_client.py) | OpenAI Chat Completions call with `response_format=json_schema`. |
| [`fingerprint.py`](../backend/pharos/lantern/fingerprint.py) | Builds the namespaced token list from the enriched output. |
| [`constellations.py`](../backend/pharos/lantern/constellations.py) | Inverted-index candidate lookup + weighted Jaccard. |
| [`worker.py`](../backend/pharos/lantern/worker.py) | The async loop: claim, enrich, persist, cluster. |

## The contract: `EnrichedArticle`

A typed JSON document that the LLM **must** produce. See [API.md](./API.md)
for the full shape. Highlights:

- `overview` — neutral 2–4 sentence summary.
- `key_points` — bullet-style facts.
- `entities`:
  - `threat_actors[].name` + `mitre_group_id`
  - `malware[].name` + `mitre_software_id`
  - `tools[]`, `vendors[]`, `companies[].role`, `products[].version`
  - `cves[]` (validated `CVE-####-#######`)
  - `mitre_groups[]`, `mitre_software[]`, `ttps_mitre[]`, `mitre_tactics[]` (all regex-validated)
  - `iocs.{ipv4, ipv6, domains, sha256, sha1, md5, urls}`
  - `sectors[]`, `countries[]`
- `severity_hint` — `low|medium|high|critical|n/a`.

OpenAI's `response_format=json_schema` makes invalid JSON impossible.
Pydantic re-validates as defense in depth. If validation fails, the
article is marked `enrichment_status='failed'` with the error captured
in `enrichment_error`; `pharos reprocess --failed-only` will requeue it.

## The fingerprint

Every enriched article gets a sorted, de-duplicated list of
**namespaced tokens** stored in `articles.fingerprint` (and exploded
into the `article_tokens` inverted index). Namespaces:

| Prefix | Meaning | Weight | Anchor tier |
|---|---|---|---|
| `cve` | CVE identifier | 15 | strong |
| `mtg` | MITRE Group ID (G####) | 12 | strong |
| `mts` | MITRE Software ID (S####) | 12 | strong |
| `thr` | threat actor canonical name | 10 | strong |
| `mal` | malware canonical name | 10 | strong |
| `ven` | vendor (e.g. `cisco`, `anthropic`) | 6 | weak |
| `com` | company / targeted org | 6 | weak |
| `pro` | product (e.g. `claude-mythos`) | 6 | weak |
| `tool` | generic tooling | 2 | context |
| `sec`, `geo`, `top` | sector / country / topic | 1 | context |
| `w` | bag-of-words fallback (title + key_points, stopwords removed) | 1 | context |

**MITRE Techniques (`T####`) and Tactics (`TA####`) are intentionally
NOT in the fingerprint.** They stay on the article entity payload and
render in the UI, but they're excluded from clustering — the LLM
over-extracts recon TTPs (`T1589` / `T1590` / `T1592` etc.) so they
cause unrelated stories to falsely cluster.

Cluster identity is "anchored" on per-event identifiers, split into two
tiers:

- **Strong anchor (≥1 shared)** is sufficient on its own — a single
  shared CVE, MITRE Group/Software ID, canonical actor or malware name
  is solid evidence of the same story.
- **Weak anchors (≥2 shared)** also qualify, but only when the two
  articles also have non-trivial *context overlap* (Jaccard of
  bag-of-words/topic/sector tokens ≥ 0.10). This blocks template
  false positives like "9to5Mac Daily" or "NYT Connections puzzle"
  where the same brand mentions recur but the actual content differs.

Both gates are implemented in `should_consider_cluster()`.

Tokens are lowercase. Why namespaces? So that the bag-of-words token
`w:apple` can never collide with the company `com:apple` or a product
`pro:apple`.

## The constellation algorithm

```text
INPUT:  new article A with fingerprint F (a set of namespaced tokens)
CONFIG: CLUSTER_WINDOW_DAYS, CLUSTER_MIN_SHARED, CLUSTER_SIM_THRESHOLD

1. Insert A's tokens into article_tokens (inverted index).

2. Find candidate articles using ONLY A's anchor tokens (per-event IDs):
       SELECT article_id, COUNT(*) AS shared
         FROM article_tokens
        WHERE token IN anchors(F)
          AND article != A
          AND published_at > now() - CLUSTER_WINDOW_DAYS
        GROUP BY article_id
        ORDER BY shared DESC LIMIT 50
   If A has no anchor tokens, A starts its own cluster -- no candidates.

3. For each candidate C:
       if not should_consider_cluster(F, tokens(C)): skip   # tiered gate
       sim = weighted_jaccard(F, tokens(C))
       if sim < CLUSTER_SIM_THRESHOLD: skip
       cluster = articles(C).story_cluster_id
       if cluster is None: skip
       track best (cluster, sim)

4. If a best cluster was found:
       attach A to it, bump member_count, update last_seen_at.
   Else:
       create a new story_cluster with A as the representative.
```

Weighted Jaccard:

```
              sum( weight(t) for t in A & B )
J(A, B) = ---------------------------------------
              sum( weight(t) for t in A | B )
```

The default thresholds (`CLUSTER_MIN_SHARED=4`, `CLUSTER_SIM_THRESHOLD=0.55`)
were chosen so that:

- Two articles sharing one CVE + one MITRE Group + a couple of words
  always cluster.
- Two articles that share only common bag-of-words tokens (`w:report`,
  `w:campaign`, ...) do not cluster.
- The candidate-lookup query stays cheap (the inverted index is
  selective enough).

If you find your stream over-clustering or under-clustering, the three
config knobs are the tuning surface. Bumping `CLUSTER_MIN_SHARED` to 6
makes the system more conservative; lowering `CLUSTER_SIM_THRESHOLD` to
0.45 makes it more aggressive.

## Reproducing a clustering decision

The `/articles/{id}/related` endpoint returns the list of constellation
siblings together with the `shared_tokens` array. That array contains
the exact tokens (sorted by weight desc) that drove the similarity
score, making every grouping decision auditable from the UI.

## Backpressure & crash safety

- Backpressure is automatic: if the LLM is slow or rate-limited,
  pending rows just accumulate. Stage 1 (ingestion) is unaffected
  because it never waits for Stage 2.
- Crash safety is automatic: if the lantern dies mid-batch, the rows
  it claimed are still marked `in_progress` and will be reset to
  `pending` either by `pharos reprocess` or by a future restart with
  the admin endpoint.
- Re-running enrichment is free: bumping any row back to `pending`
  reprocesses it (after a prompt change, for example) without any
  external infrastructure.

## Cost / throughput

With `gpt-4o-mini` at `LANTERN_CONCURRENCY=8` we measure roughly:

- 30 articles / minute steady state.
- ~3000 input tokens / article (truncated to 12k chars of body).
- ~600 output tokens / article (the JSON document).

Caching by `content_hash` (planned) will eliminate re-cost on
re-enrichment.
