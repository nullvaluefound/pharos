"""Prompt templates for threat-intel report generation.

Two structural modes:
  - BLUF (default): Bottom Line Up Front -- key judgments, then context
  - custom: user supplies an ordered list of section headings

Three audience modes:
  - executive : non-technical leadership; outcomes, business impact, risk
  - technical : SOC / IR / threat-intel analysts; IOCs, TTPs, CVEs, MITRE IDs
  - both      : combined report with a clearly-marked "Executive Summary"
                section AND a "Technical Details" section

Three length targets (rough token budgets):
  - short  : ~600-1200 words   (~1-2 printed pages)
  - medium : ~1200-2200 words  (~2-3 pages)
  - long   : ~2200-3500 words  (~3-4 pages)
"""
from __future__ import annotations

from typing import Iterable

# ---------------------------------------------------------------------------
# Length budgets
# ---------------------------------------------------------------------------
LENGTH_BUDGETS: dict[str, tuple[int, int, int]] = {
    # (min_words, max_words, max_output_tokens)
    "short":  (600, 1200, 2400),
    "medium": (1200, 2200, 4000),
    "long":   (2200, 3500, 6000),
}


def length_targets(length: str) -> tuple[int, int, int]:
    return LENGTH_BUDGETS.get(length, LENGTH_BUDGETS["short"])


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
def _bluf_outline() -> str:
    return (
        "Use a Bottom-Line-Up-Front (BLUF) structure with these sections "
        "(use them as exact H2 headings):\n"
        "  ## Bottom Line Up Front\n"
        "  ## Key Judgments\n"
        "  ## Background\n"
        "  ## Detailed Findings\n"
        "  ## Recommendations\n"
        "  ## Sources\n"
    )


def _custom_outline(sections: list[str]) -> str:
    body = "\n".join(f"  ## {s.strip()}" for s in sections if s.strip())
    return (
        "Use the user-defined section headings exactly as listed (in order, "
        "as H2 headings):\n" + body +
        "\n  ## Sources\n"
    )


def _audience_block(audience: str) -> str:
    if audience == "executive":
        return (
            "AUDIENCE: Executive leadership.\n"
            "  - Lead with business impact: what does this mean for the\n"
            "    organization, customers, regulators, share price?\n"
            "  - Use plain English. Avoid jargon. Spell out acronyms first use.\n"
            "  - Quantify risk in concrete terms when possible (number of\n"
            "    affected systems / customers, breach scope, exploitation\n"
            "    likelihood).\n"
            "  - Recommendations should be at the policy / investment level.\n"
        )
    if audience == "technical":
        return (
            "AUDIENCE: SOC, IR, and threat-intel analysts.\n"
            "  - Be precise with MITRE Tactic / Technique IDs (TA####, T####,\n"
            "    T####.###), CVE identifiers, CVSS scores, malware family\n"
            "    names, threat actor / intrusion set names + MITRE Group IDs\n"
            "    (G####), and software IDs (S####). Never invent any of these.\n"
            "  - Surface IOCs (IPv4/6, domains, URLs, file hashes) verbatim\n"
            "    from the source articles when present.\n"
            "  - Recommendations should be detection / mitigation / hunting at\n"
            "    the control / signature / playbook level.\n"
        )
    # both
    return (
        "AUDIENCE: Mixed (executive + technical readers).\n"
        "  - Open every report with an 'Executive Summary' subsection inside\n"
        "    the opening section that is readable in <60 seconds, no jargon,\n"
        "    business-impact framed.\n"
        "  - Then provide deeper 'Technical Details' coverage within the\n"
        "    appropriate section(s) using exact MITRE Tactic / Technique IDs\n"
        "    (TA####, T####, T####.###), CVEs, CVSS, threat-actor names with\n"
        "    MITRE Group IDs (G####), malware Software IDs (S####), and IOCs\n"
        "    (IPs, domains, URLs, hashes) as drawn from the source articles.\n"
        "  - Recommendations should have an executive line item AND a\n"
        "    technical detection / mitigation line item where applicable.\n"
    )


def system_prompt(*, structure_kind: str, sections: list[str] | None,
                  audience: str, length: str) -> str:
    min_w, max_w, _ = length_targets(length)
    outline = (
        _bluf_outline()
        if structure_kind == "BLUF" or not sections
        else _custom_outline(sections)
    )
    return f"""\
You are Pharos, a senior threat-intelligence analyst. The user is requesting a
finished written report drawn ENTIRELY from the supplied corpus of enriched
articles. Do not introduce facts that are not derivable from the corpus or its
provided structured metadata.

OUTPUT FORMAT
- Plain Markdown (no front-matter, no preamble, no JSON).
- Begin directly with the first H2 heading -- do NOT include the report title
  as an H1 (the UI renders it separately).
- Use Markdown tables for IOC / CVE / detection-rule lists where helpful.
- Cite source articles inline using [bracketed numbers], where the number is
  the 1-indexed position in the corpus listing the user provides. Compile a
  numbered ## Sources section at the end with each cited article's title and URL.

LENGTH
- Target {min_w}-{max_w} words. Write to that target -- do not add filler to
  reach it; do not omit material to hide under it.

{_audience_block(audience)}

STRUCTURE
{outline}

ANALYTICAL DISCIPLINE
- Distinguish reported fact (what the source said) from analytic judgment
  (what you conclude). Mark judgments with explicit confidence language
  ("high confidence", "moderate confidence", "low confidence") and a brief
  rationale.
- Where multiple sources corroborate the same fact, cite all of them.
- Where sources conflict, surface the conflict explicitly.
- Be conservative. If the corpus does not support a claim, say so.
- Never invent CVE IDs, MITRE IDs, IOCs, or attribution.
"""


# ---------------------------------------------------------------------------
# User prompt
# ---------------------------------------------------------------------------
def article_block(idx: int, *, title: str | None, url: str,
                  published_at: str | None, feed_title: str | None,
                  overview: str | None, severity: str | None,
                  enriched: dict | None) -> str:
    """Render one article as a numbered Markdown block for the user prompt.

    We feed the LLM the enriched JSON (small, structured) plus a 1-line
    overview rather than the full body -- keeps prompt tokens tractable
    even for large corpora.
    """
    lines: list[str] = []
    lines.append(f"### [{idx}] {title or '(untitled)'}")
    meta_bits: list[str] = []
    if feed_title:
        meta_bits.append(feed_title)
    if published_at:
        meta_bits.append(published_at[:10])
    if severity:
        meta_bits.append(f"severity: {severity}")
    if meta_bits:
        lines.append(" | ".join(meta_bits))
    lines.append(f"URL: {url}")
    if overview:
        lines.append(overview.strip())

    if enriched and isinstance(enriched, dict):
        e = enriched.get("entities") or {}
        bits: list[str] = []

        def _names(items, key: str = "name") -> list[str]:
            out: list[str] = []
            for it in (items or [])[:10]:
                if isinstance(it, dict):
                    n = it.get(key)
                    if n:
                        out.append(str(n))
                elif it:
                    out.append(str(it))
            return out

        actors = _names(e.get("threat_actors"))
        malware = _names(e.get("malware"))
        cves = [c for c in (e.get("cves") or [])[:10] if c]
        ttps = [t for t in (e.get("ttps_mitre") or [])[:10] if t]
        tactics = [t for t in (e.get("mitre_tactics") or [])[:10] if t]
        groups = [g for g in (e.get("mitre_groups") or [])[:10] if g]
        sectors = [s for s in (e.get("sectors") or [])[:10] if s]
        countries = [c for c in (e.get("countries") or [])[:10] if c]
        vendors = _names(e.get("vendors"))
        products = _names(e.get("products"))

        if actors:    bits.append(f"Actors: {', '.join(actors)}")
        if groups:    bits.append(f"MITRE Groups: {', '.join(groups)}")
        if malware:   bits.append(f"Malware: {', '.join(malware)}")
        if cves:      bits.append(f"CVEs: {', '.join(cves)}")
        if ttps:      bits.append(f"TTPs: {', '.join(ttps)}")
        if tactics:   bits.append(f"Tactics: {', '.join(tactics)}")
        if sectors:   bits.append(f"Sectors: {', '.join(sectors)}")
        if countries: bits.append(f"Countries: {', '.join(countries)}")
        if vendors:   bits.append(f"Vendors: {', '.join(vendors)}")
        if products:  bits.append(f"Products: {', '.join(products)}")
        if bits:
            lines.append("Metadata: " + " | ".join(bits))

    return "\n".join(lines)


def build_user_prompt(*, name: str, scope_text: str,
                      article_blocks: Iterable[str]) -> str:
    body = "\n\n".join(article_blocks)
    return (
        f"REPORT TITLE: {name}\n\n"
        f"SCOPE / FILTER NOTE FROM USER:\n{scope_text or '(none specified)'}\n\n"
        f"CORPUS ({sum(1 for _ in [body])} articles): see numbered listing below.\n"
        f"-----\n{body}\n-----\n\n"
        "Write the report now in Markdown, beginning with the first H2 heading."
    )
