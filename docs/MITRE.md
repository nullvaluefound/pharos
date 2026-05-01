# MITRE ATT&CK Integration

Pharos treats MITRE ATT&CK identifiers as **first-class fields**, not as
free-text. Every MITRE identifier emitted by the lantern is regex-validated,
normalized to canonical form, persisted as a typed `entities` row, indexed
in the `article_tokens` inverted index for clustering, exposed by the
search API, and decorated with the canonical `attack.mitre.org` URL when
returned to the frontend.

## Identifier formats

| Kind | Format | Example | Where it appears |
|---|---|---|---|
| Group | `G####` | `G0016` (APT29) | `entities.mitre_groups`, `threat_actors[].mitre_group_id` |
| Software | `S####` | `S0154` (Cobalt Strike) | `entities.mitre_software`, `malware[].mitre_software_id` |
| Technique | `T####` | `T1566` | `entities.ttps_mitre` |
| Sub-technique | `T####.###` | `T1566.001` | `entities.ttps_mitre` |
| Tactic | `TA####` | `TA0001` (Initial Access) | `entities.mitre_tactics` |

The validation lives in [`pharos.lantern.mitre`](../backend/pharos/lantern/mitre.py).
Anything that doesn't match the regex is rejected at the pydantic boundary.

## How they get there

1. **Prompt.** The system prompt
   ([`pharos/lantern/prompts.py`](../backend/pharos/lantern/prompts.py))
   *requires* the LLM to populate the MITRE fields whenever the entity is in
   the ATT&CK knowledge base, and to use canonical IDs (e.g. `G0016`, not
   "G16" or "g0016"). Sub-techniques must be reported alongside their parent.

2. **Schema validation.** The pydantic models
   ([`pharos/lantern/schema.py`](../backend/pharos/lantern/schema.py))
   validate every ID with the corresponding regex from `mitre.py`. Invalid
   IDs cause the whole enrichment to fail (and the article is marked
   `failed`, picked up later by `pharos reprocess --failed-only`).

3. **Persistence.** The lantern worker
   ([`pharos/lantern/worker.py`](../backend/pharos/lantern/worker.py))
   inserts each MITRE ID into the `entities` table with the corresponding
   `type` (`mitre_group`, `mitre_software`, `ttp_mitre`, `mitre_tactic`)
   and links it to the article via `article_entities`. This is what makes
   the search API able to filter "all articles mentioning G0016".

4. **Clustering.** The fingerprint builder
   ([`pharos/lantern/fingerprint.py`](../backend/pharos/lantern/fingerprint.py))
   adds the canonical IDs as namespaced tokens:
   - `mtg:g0016` (Group)
   - `mts:s0154` (Software)
   - `ttp:t1566.001` plus `ttp:t1566` (sub-technique always implies parent)
   - `mta:ta0001` (Tactic)

   These tokens carry the **highest weights** in the constellation
   clusterer (`mtg` and `mts` weight 5; `ttp` weight 4; `mta` weight 3).
   The result: two articles that both mention `G0016` and `T1566.001` will
   cluster together even if they describe APT29 with different language
   and target different victims.

5. **Frontend.** The article detail endpoint
   ([`pharos/api/routes/articles.py`](../backend/pharos/api/routes/articles.py))
   adds an `entities.mitre_links` decoration with the canonical
   `attack.mitre.org` URL for each ID, so the UI renders every MITRE entity
   as a clickable deep link without re-implementing URL construction.

## Searching by MITRE IDs

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "any_of": { "mitre_group": ["g0016"], "ttp_mitre": ["t1566.001"] },
        "since_days": 30
      }'
```

(Use lowercase canonical strings in the search body. The validators
upper-case for storage; the search side lower-cases for matching.)

## Worked example

Two articles published the same day:

> **BleepingComputer**: "APT29 abuses CVE-2024-12345 in Microsoft Exchange to phish EU diplomats"
>
> **The Register**: "Russian state hackers exploit Exchange zero-day in spear-phishing campaign"

After enrichment, both produce overlapping MITRE entities:

| Field | BleepingComputer | The Register |
|---|---|---|
| `threat_actors[].mitre_group_id` | `G0016` | `G0016` |
| `mitre_groups` | `["G0016"]` | `["G0016"]` |
| `ttps_mitre` | `["T1566", "T1566.001"]` | `["T1566", "T1566.001"]` |
| `mitre_tactics` | `["TA0001"]` | `["TA0001"]` |
| `cves` | `["CVE-2024-12345"]` | `[]` |

Their fingerprints share the high-weight tokens `mtg:g0016`,
`ttp:t1566.001`, `ttp:t1566`, `mta:ta0001` (plus assorted lower-weight
words). The weighted Jaccard score lands well above
`CLUSTER_SIM_THRESHOLD`, so they get the same `story_cluster_id`. The
`/related` endpoint will then surface them as a single constellation,
with `shared_tokens` showing the user *exactly* which MITRE IDs caused
the grouping.

## Future work

- Bundle the MITRE STIX 2.1 export so we can resolve `G0016 ->
  "APT29 (Cozy Bear, NOBELIUM)"` and offer canonical-name autocomplete
  in the filter UI.
- Validate `mitre_software_id` claims against the official software
  catalog so the LLM cannot invent fictitious S-numbers.
- Add a `mitre_relations` view computing pivots like "all techniques
  used by this group" by joining article-level extractions.
