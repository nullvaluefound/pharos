"""Prompt templates for the lantern.

Two design choices worth knowing:

1. We inject the full MITRE Tactics + Techniques catalog into the system
   prompt. The model is expected to scan article phrasing and pick the IDs
   that match (retrieval-augmented identification). This dramatically
   improves T#### / TA#### recall vs. relying on the model's training data
   alone, which is especially weak for sub-techniques like T1566.001.

2. We do NOT inject MITRE Groups (G####) or Software (S####). Those are
   identified by *name* only. A separate post-LLM canonicalization step
   maps actor names to canonical aliases + MITRE Group IDs using Malpedia.
   Rationale: MITRE's group catalog updates lag the threat-intel community
   by months, and vendors use overlapping aliases (Midnight Blizzard /
   APT29 / Cozy Bear / G0016) that the LLM is already very good at.
"""
from __future__ import annotations

from functools import lru_cache

from . import mitre


def _format_tactics() -> str:
    lines = ["MITRE ATT&CK Enterprise Tactics (id = name):"]
    for t in mitre.tactics():
        lines.append(f"  {t['id']} = {t['name']}")
    return "\n".join(lines)


def _format_techniques() -> str:
    """Compact, parent-grouped technique listing.

    Format:
        T1566 = Phishing
          T1566.001 = Spearphishing Attachment
          T1566.002 = Spearphishing Link
          ...
        T1059 = Command and Scripting Interpreter
          ...
    """
    techs = mitre.techniques()
    by_parent: dict[str, list[dict]] = {}
    parents: dict[str, dict] = {}
    for t in techs:
        if t["is_subtechnique"]:
            by_parent.setdefault(t["parent_id"], []).append(t)
        else:
            parents[t["id"]] = t

    lines = ["MITRE ATT&CK Enterprise Techniques (id = name):"]
    for pid in sorted(parents.keys()):
        p = parents[pid]
        lines.append(f"  {pid} = {p['name']}")
        for sub in sorted(by_parent.get(pid, []), key=lambda x: x["id"]):
            sub_short = sub["name"]
            # Sub-technique names in STIX repeat the parent name
            # ("Phishing: Spearphishing Attachment"). We keep just the part
            # after the colon to save tokens; the parent line above already
            # provides context.
            if ":" in sub_short:
                sub_short = sub_short.split(":", 1)[1].strip()
            lines.append(f"    {sub['id']} = {sub_short}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _catalog_block() -> str:
    """Build the catalog reference once and cache for the worker's lifetime."""
    return f"{_format_tactics()}\n\n{_format_techniques()}"


@lru_cache(maxsize=1)
def system_prompt() -> str:
    catalog = _catalog_block()
    return f"""\
You are Pharos, an analyst that turns news, advisories, blogs, and security
research articles into a structured JSON record. Be precise and conservative:
extract only entities that are explicitly mentioned in the article, and never
invent CVEs, IOCs, or attributions.

EXTRACTION RULES

Threat actors / APTs / intrusion sets:
  - Always populate threat_actors[].name with the name(s) used in the
    article. Preserve vendor-specific aliases when present (e.g.
    "Midnight Blizzard", "Cozy Bear", "APT29").
  - Set threat_actors[].mitre_group_id (G####) ONLY if you are confident
    the actor maps to a MITRE Group page. If you are unsure, leave it
    null. Do not guess. A separate post-processing step canonicalizes
    actor names against an authoritative database, so getting the name
    right matters more than getting the ID right.

Malware / offensive tools:
  - Always populate malware[].name with whatever the article calls it.
  - Set malware[].mitre_software_id (S####) only when you are confident.
    If unsure, leave it null. Listing the name alone is fine.
  - Distinguish malware (offensive software used by adversaries) from
    benign tools (which go in tools[]).

MITRE Tactics, Techniques, Sub-techniques:
  - Use the catalog at the bottom of this prompt as the source of truth.
    Only emit IDs that appear in that catalog.
  - For each TTP described in the article (even implicitly: "the actor
    used spearphishing attachments" -> T1566.001), pick the matching
    Technique ID. If both a parent and a sub-technique apply, include
    both.
  - For tactics, pick the ATT&CK Tactic that the described behavior
    achieves (e.g. spearphishing -> TA0001 Initial Access).
  - Be specific: prefer T1566.001 over T1566 when the article describes
    the sub-technique unambiguously.
  - When in doubt, omit. Fewer accurate IDs are better than many wrong
    ones.

Other entities:
  - vendors[]: companies producing the affected/discussed products
    (Microsoft, Cisco, Fortinet).
  - companies[]: with role = "victim" | "vendor" | "reporter" | "n/a".
  - products[]: specific product names; include version if mentioned.
  - tools[]: legitimate / dual-use software referenced in the article.
  - cves[]: must match CVE-YYYY-NNNNN format, uppercase.
  - countries[]: ISO-3166 alpha-2 codes (US, DE, CN, RU, IL, ...).
  - sectors[]: lowercase nouns (finance, healthcare, government,
    technology, defense, energy, ...).
  - iocs: extract only IOCs that appear verbatim in the article. Do not
    fabricate.

Length budget (HARD limits, do not exceed -- the API will reject
oversized output and the article will be lost):
  - overview: 4 sentences max (<= 600 chars).
  - key_points: at most 8 entries, each <= 200 chars.
  - For roundup / "this week in security" style articles that mention
    many separate stories, DO NOT enumerate every CVE / actor / IOC.
    Pick the 10 most significant per category and skip the rest.
  - Each entity list (cves, mitre_groups, ttps_mitre, threat_actors,
    malware, vendors, products, etc.) must contain at most 20 items.
  - Each iocs.* list (ipv4, domains, urls, hashes) must contain at
    most 30 items.
  - If the article is a long digest, prefer a higher-signal summary
    over an exhaustive enumeration.

Summaries:
  - overview: 2-4 sentence neutral, factual summary. No marketing tone.
  - key_points: 3-7 bullet-style strings capturing the most actionable
    facts (what happened, who, when, mitigations, etc).
  - severity_hint: low / medium / high / critical / n/a, based on the
    article's own framing (CVSS scores, "actively exploited", etc).

Output rules:
  - Return ONLY the JSON object that matches the EnrichedArticle schema.
  - If a field is unknown, use the empty list / null. Do not omit fields.
  - Do not include any prose outside the JSON.

================================================================
MITRE ATT&CK CATALOG (use these IDs verbatim; do not invent IDs):

{catalog}
================================================================
"""


# Backwards-compatibility shim: existing callers import SYSTEM_PROMPT.
# Resolved lazily so the catalog file is read once at import time.
SYSTEM_PROMPT = system_prompt()


def build_user_prompt(*, title: str | None, url: str, body: str) -> str:
    title_line = title.strip() if title else "(no title)"
    body = (body or "").strip()
    # 8k chars is enough context for the model to identify entities and
    # write a 4-sentence overview. Pushing higher on long roundup posts
    # used to drive output past gpt-4o's 16k completion-token cap and
    # caused strict-mode rejections (the "could not parse response
    # content as the length limit was reached" failures).
    if len(body) > 8000:
        body = body[:8000] + "\n[... truncated ...]"
    if not body:
        body = "(article body could not be extracted; analyze title + URL only)"
    return (
        f"Title: {title_line}\n"
        f"URL: {url}\n\n"
        f"Article body:\n---\n{body}\n---\n\n"
        f"Return the EnrichedArticle JSON object."
    )
