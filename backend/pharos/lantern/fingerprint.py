"""Deterministic keyword fingerprint for cross-source story clustering.

Tokens are namespaced by entity type so collisions between e.g. a vendor
named "Apple" and the fruit word "apple" cannot happen. High-signal entity
types (CVEs, MITRE TTPs, threat actors, malware) carry larger weights in the
weighted Jaccard scoring done in :mod:`pharos.lantern.constellations`.
"""
from __future__ import annotations

import re
from typing import Iterable

from .schema import EnrichedArticle

# Curated stopword list. Intentionally short -- entity-namespaced tokens carry
# the bulk of the signal, so the bag-of-words tail is just for tiebreaking.
STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then else of in on at to from by for with as is are
    was were be been being have has had do does did this that these those it
    its their they them we us our you your he she his her i me my mine ours
    not no yes so very can could should would may might must shall will just
    about into over under between within without while because since until
    again further also however therefore thus more most less least new update
    today yesterday tomorrow week month year time year-old said says reports
    according
    """.split()
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-]+")
_PUNCT_RE = re.compile(r"[^a-z0-9\-]+")

# Token namespace prefixes. Keep these short for compact storage.
# MITRE ATT&CK identifiers each get their own namespace so that, e.g., a
# "thr:apt29" name token is distinct from the canonical "mtg:g0016" group ID.
NS_THREAT_ACTOR = "thr"     # threat actor canonical name (e.g. apt29)
NS_MALWARE = "mal"          # malware canonical name (e.g. cobaltstrike)
NS_TOOL = "tool"
NS_VENDOR = "ven"
NS_COMPANY = "com"
NS_PRODUCT = "pro"
NS_CVE = "cve"              # CVE-#### identifier
NS_MITRE_GROUP = "mtg"      # MITRE Group ID (G####)
NS_MITRE_SOFTWARE = "mts"   # MITRE Software ID (S####)
NS_MITRE_TACTIC = "mta"     # MITRE Tactic ID (TA####)
NS_TTP = "ttp"              # MITRE Technique / Sub-technique (T####, T####.###)
NS_SECTOR = "sec"
NS_COUNTRY = "geo"
NS_TOPIC = "top"
NS_WORD = "w"


def _normalize(name: str) -> str:
    name = name.strip().lower()
    name = _PUNCT_RE.sub("-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name


def _tokenize_text(text: str) -> Iterable[str]:
    for match in _WORD_RE.findall(text):
        token = match.lower()
        if len(token) <= 2:
            continue
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        yield token


def build_fingerprint(article: EnrichedArticle, *, title: str | None) -> list[str]:
    """Return a sorted, de-duplicated list of namespaced tokens."""
    tokens: set[str] = set()

    e = article.entities
    for ne in e.threat_actors:
        n = _normalize(ne.name)
        if n:
            tokens.add(f"{NS_THREAT_ACTOR}:{n}")
        if ne.mitre_group_id:
            tokens.add(f"{NS_MITRE_GROUP}:{ne.mitre_group_id.lower()}")
    for ne in e.malware:
        n = _normalize(ne.name)
        if n:
            tokens.add(f"{NS_MALWARE}:{n}")
        if ne.mitre_software_id:
            tokens.add(f"{NS_MITRE_SOFTWARE}:{ne.mitre_software_id.lower()}")
    for ne in e.tools:
        n = _normalize(ne.name)
        if n:
            tokens.add(f"{NS_TOOL}:{n}")
    for ne in e.vendors:
        n = _normalize(ne.name)
        if n:
            tokens.add(f"{NS_VENDOR}:{n}")
    for ne in e.companies:
        n = _normalize(ne.name)
        if n:
            tokens.add(f"{NS_COMPANY}:{n}")
    for pe in e.products:
        n = _normalize(pe.name)
        if n:
            tokens.add(f"{NS_PRODUCT}:{n}")

    for cve in e.cves:
        n = _normalize(cve)
        if n:
            tokens.add(f"{NS_CVE}:{n}")

    for ttp in e.ttps_mitre:
        n = _normalize(ttp)
        if n:
            tokens.add(f"{NS_TTP}:{n}")
            # Sub-techniques (T####.###) also collapse to the parent technique
            # so that two articles referencing different sub-techniques of the
            # same parent still share a clustering signal.
            if "." in n:
                parent = n.split(".", 1)[0]
                tokens.add(f"{NS_TTP}:{parent}")

    for gid in e.mitre_groups:
        tokens.add(f"{NS_MITRE_GROUP}:{gid.lower()}")
    for sid in e.mitre_software:
        tokens.add(f"{NS_MITRE_SOFTWARE}:{sid.lower()}")
    for tid in e.mitre_tactics:
        tokens.add(f"{NS_MITRE_TACTIC}:{tid.lower()}")

    for s in e.sectors:
        n = _normalize(s)
        if n:
            tokens.add(f"{NS_SECTOR}:{n}")
    for c in e.countries:
        n = _normalize(c)
        if n:
            tokens.add(f"{NS_COUNTRY}:{n}")
    for t in article.topics:
        n = _normalize(t)
        if n:
            tokens.add(f"{NS_TOPIC}:{n}")

    body_text = " ".join(filter(None, [title or "", *article.key_points]))
    for word in _tokenize_text(body_text):
        tokens.add(f"{NS_WORD}:{word}")

    return sorted(tokens)
