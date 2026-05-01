"""Pydantic schema for LLM-enriched article output.

This is the strict JSON contract we ask the LLM to satisfy via OpenAI's
structured outputs. Validation happens server-side too.

MITRE ATT&CK identifiers are first-class fields:
  - ``mitre_groups``     : list of MITRE Group IDs (G####, e.g. G0016 = APT29)
  - ``ttps_mitre``       : list of MITRE Technique / Sub-technique IDs
                           (T#### or T####.###, e.g. T1566.001)
  - ``mitre_software``   : list of MITRE Software IDs (S####, e.g. S0154 = Cobalt Strike)
  - ``mitre_tactics``    : list of MITRE Tactic IDs   (TA####, e.g. TA0001 = Initial Access)

For threat actors and malware we keep both a free-text canonical name AND
(where the LLM can identify it) the corresponding MITRE Group / Software ID
so users can pivot directly into attack.mitre.org.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from . import mitre


class NamedEntity(BaseModel):
    name: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    role: str | None = None


class ThreatActorEntity(NamedEntity):
    """A threat actor / APT / intrusion set.

    ``mitre_group_id`` is the MITRE Group ID (G####) when known, e.g. APT29 -> G0016.
    """
    mitre_group_id: str | None = Field(
        default=None,
        description="MITRE Group ID (format G####), if known.",
    )

    @field_validator("mitre_group_id")
    @classmethod
    def _validate_group(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = mitre.normalize(v)
        # Drop non-conforming values silently rather than killing the whole
        # article. Group IDs are not bundled with the prompt (the model is
        # supposed to infer them from training knowledge + Malpedia), so
        # hallucinations are expected and we just throw them out.
        if not mitre.is_group(v):
            return None
        return v


class MalwareEntity(NamedEntity):
    """Malware / tool tracked in the MITRE Software catalog.

    ``mitre_software_id`` is the MITRE Software ID (S####), if known.
    """
    mitre_software_id: str | None = Field(
        default=None,
        description="MITRE Software ID (format S####), if known.",
    )

    @field_validator("mitre_software_id")
    @classmethod
    def _validate_software(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = mitre.normalize(v)
        if not mitre.is_software(v):
            return None
        return v


class CompanyEntity(NamedEntity):
    role: str | None = Field(default=None, description="victim | vendor | reporter | n/a")


class ProductEntity(NamedEntity):
    version: str | None = None


class IOCs(BaseModel):
    ipv4: list[str] = Field(default_factory=list)
    ipv6: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    sha256: list[str] = Field(default_factory=list)
    sha1: list[str] = Field(default_factory=list)
    md5: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


def _validate_id_list(values: list[str], predicate, label: str) -> list[str]:
    """Normalize, drop unknown/malformed IDs silently, and de-duplicate.

    We deliberately do NOT raise on a single bad ID -- the model occasionally
    hallucinates a plausible-looking but non-existent identifier, and losing
    the entire article over that is worse than dropping the offender. The
    list is empty-tolerant by design.
    """
    out: list[str] = []
    for v in values:
        if not v:
            continue
        norm = mitre.normalize(v)
        if not predicate(norm):
            continue
        out.append(norm)
    # de-duplicate, preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            deduped.append(v)
    return deduped


class Entities(BaseModel):
    threat_actors: list[ThreatActorEntity] = Field(default_factory=list)
    malware: list[MalwareEntity] = Field(default_factory=list)
    tools: list[NamedEntity] = Field(default_factory=list)
    vendors: list[NamedEntity] = Field(default_factory=list)
    companies: list[CompanyEntity] = Field(default_factory=list)
    products: list[ProductEntity] = Field(default_factory=list)

    cves: list[str] = Field(default_factory=list)

    # MITRE ATT&CK structured identifiers
    mitre_groups: list[str] = Field(
        default_factory=list,
        description="MITRE Group IDs (G####). May be richer than threat_actors[].mitre_group_id "
                    "if the article mentions groups not represented as named entities.",
    )
    ttps_mitre: list[str] = Field(
        default_factory=list,
        description="MITRE Technique or Sub-technique IDs (T#### or T####.###).",
    )
    mitre_software: list[str] = Field(
        default_factory=list,
        description="MITRE Software IDs (S####).",
    )
    mitre_tactics: list[str] = Field(
        default_factory=list,
        description="MITRE Tactic IDs (TA####).",
    )

    iocs: IOCs = Field(default_factory=IOCs)
    sectors: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)

    @field_validator("cves")
    @classmethod
    def _normalize_cves(cls, v: list[str]) -> list[str]:
        import re

        cve_re = re.compile(r"^CVE-\d{4}-\d{4,7}$")
        out: list[str] = []
        for c in v:
            norm = c.strip().upper()
            if cve_re.match(norm):
                out.append(norm)
        return list(dict.fromkeys(out))

    @field_validator("mitre_groups")
    @classmethod
    def _validate_groups(cls, v: list[str]) -> list[str]:
        return _validate_id_list(v, mitre.is_group, "MITRE Group ID")

    @field_validator("ttps_mitre")
    @classmethod
    def _validate_techniques(cls, v: list[str]) -> list[str]:
        # is_known_technique cross-checks against the bundled catalog so a
        # well-formed but non-existent T####.### gets dropped quietly.
        return _validate_id_list(v, mitre.is_known_technique, "MITRE Technique ID")

    @field_validator("mitre_software")
    @classmethod
    def _validate_software(cls, v: list[str]) -> list[str]:
        return _validate_id_list(v, mitre.is_software, "MITRE Software ID")

    @field_validator("mitre_tactics")
    @classmethod
    def _validate_tactics(cls, v: list[str]) -> list[str]:
        return _validate_id_list(v, mitre.is_known_tactic, "MITRE Tactic ID")


ContentType = Literal[
    "news",
    "advisory",
    "blog",
    "research",
    "vendor_post",
    "leak",
    "podcast",
    "newsletter",
    "video",
    "other",
]
SeverityHint = Literal["low", "medium", "high", "critical", "n/a"]


class EnrichedArticle(BaseModel):
    overview: str = Field(description="2-4 sentence neutral summary.")
    language: str = Field(default="en")
    content_type: ContentType = Field(default="news")
    topics: list[str] = Field(default_factory=list)
    entities: Entities = Field(default_factory=Entities)
    severity_hint: SeverityHint = Field(default="n/a")
    is_duplicate_of: int | None = None
    key_points: list[str] = Field(default_factory=list)


def openai_json_schema() -> dict:
    """Return the JSON Schema dict to pass to the OpenAI API."""
    schema = EnrichedArticle.model_json_schema()
    schema["additionalProperties"] = False
    return schema
