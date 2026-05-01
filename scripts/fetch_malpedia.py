"""Fetch Malpedia actor + family data and bake a compact lookup table.

Malpedia is the authoritative open dataset for threat actor / malware
naming and aliasing maintained by Fraunhofer FKIE. We use it to
canonicalize names extracted by the LLM during post-processing:

    LLM emits "Midnight Blizzard"   ->  canonical "APT29", G0016
    LLM emits "BRONZE SILHOUETTE"   ->  canonical "Volt Typhoon"
    LLM emits "Cobalt Strike"       ->  canonical "Cobalt Strike", S0154

This script pulls the public API (no auth required) and writes a small
JSON file shipped with the backend package:

    backend/pharos/lantern/data/malpedia.json

Schema:
    {
      "version": "<iso timestamp>",
      "source":  "https://malpedia.caad.fkie.fraunhofer.de/",
      "actors": {
          "<lowercase alias>": {
              "canonical": "APT29",
              "mitre_group_id": "G0016",   # null if no ATT&CK page
              "country": "RU",             # ISO alpha-2 if known
              "aliases": ["Cozy Bear", "The Dukes", "Midnight Blizzard", ...]
          },
          ...
      },
      "families": {
          "<lowercase alias>": {
              "canonical": "Cobalt Strike",
              "mitre_software_id": "S0154",
              "platforms": ["win"],
              "actors": ["FIN6", "FIN7", "Magic Hound", ...],
              "aliases": ["beacon", ...]
          },
          ...
      }
    }

License: Malpedia data is CC BY-NC-SA 4.0. Pharos is non-commercial open
source so this is fine; downstream redistribution must keep attribution.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path

ACTORS_URL = "https://malpedia.caad.fkie.fraunhofer.de/api/get/actors"
FAMILIES_URL = "https://malpedia.caad.fkie.fraunhofer.de/api/get/families"

OUT = (
    Path(__file__).resolve().parents[1]
    / "backend" / "pharos" / "lantern" / "data" / "malpedia.json"
)

GROUP_RE = re.compile(r"attack\.mitre\.org/groups/(G\d{4})", re.I)
SOFTWARE_RE = re.compile(r"attack\.mitre\.org/software/(S\d{4})", re.I)


def _http_get(url: str) -> bytes:
    print(f"GET {url} ...", flush=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "pharos-malpedia-fetcher/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    print(f"  -> {len(data) / 1024:.1f} KB")
    return data


def _normalize_alias(s: str) -> str:
    """Lowercase + collapse whitespace + strip punctuation noise so 'APT 29',
    'apt29', 'APT-29' all collide on the same key."""
    s = s.strip().lower()
    s = re.sub(r"[\s\-\u2010-\u2015]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _extract_mitre_id(refs: list[str], pattern: re.Pattern) -> str | None:
    if not refs:
        return None
    for url in refs:
        m = pattern.search(url or "")
        if m:
            return m.group(1).upper()
    return None


def build_actors(raw: dict) -> dict:
    """Build the alias -> canonical actor map."""
    actors: dict[str, dict] = {}
    skipped = 0
    for canonical, payload in raw.items():
        meta = payload.get("meta") or {}
        synonyms: list[str] = list(meta.get("synonyms") or [])

        # Vendor-attributed names show up as `origin:<name>: <vendor>` in meta
        # (e.g. origin:BRONZE SILHOUETTE: Secureworks). Treat those keys as
        # additional aliases.
        for k in meta.keys():
            if k.startswith("origin:"):
                alias = k.split(":", 1)[1].strip()
                if alias and alias not in synonyms and alias != canonical:
                    synonyms.append(alias)

        # Refs sometimes link to an attack.mitre.org group page.
        refs = meta.get("refs") or []
        mitre_group_id = _extract_mitre_id(refs, GROUP_RE)

        country = (meta.get("country") or "").strip().upper() or None
        if country and len(country) > 3:
            country = None  # malpedia occasionally has free-text countries

        # Build the alias list including the canonical itself for lookups.
        all_aliases = [canonical] + synonyms
        # de-duplicate while preserving order
        seen: set[str] = set()
        unique = []
        for a in all_aliases:
            key = _normalize_alias(a)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(a)

        record = {
            "canonical": canonical,
            "mitre_group_id": mitre_group_id,
            "country": country,
            "aliases": unique,
        }

        registered = 0
        for alias in unique:
            key = _normalize_alias(alias)
            if not key:
                continue
            # If two actors share an alias, keep the one that has a MITRE
            # ID (more authoritative), else keep the one with more aliases.
            existing = actors.get(key)
            if existing is None:
                actors[key] = record
                registered += 1
            else:
                if mitre_group_id and not existing.get("mitre_group_id"):
                    actors[key] = record
                elif not existing.get("mitre_group_id") and len(unique) > len(
                    existing.get("aliases", [])
                ):
                    actors[key] = record
                # else: leave existing
        if registered == 0:
            skipped += 1

    print(f"  actors: {len(raw)} canonical, {len(actors)} alias keys (skipped {skipped})")
    return actors


def build_families(raw: dict) -> dict:
    families: dict[str, dict] = {}
    for family_key, payload in raw.items():
        common_name = (payload.get("common_name") or "").strip() or family_key
        alt_names = payload.get("alt_names") or []
        attribution = payload.get("attribution") or []
        urls = payload.get("urls") or []

        # Family keys in malpedia are like "win.cobalt_strike" - the prefix
        # is the platform. Useful metadata.
        platform = family_key.split(".", 1)[0] if "." in family_key else None

        mitre_software_id = _extract_mitre_id(urls, SOFTWARE_RE)

        all_aliases = [common_name] + list(alt_names)
        # The malpedia key (e.g. win.cobalt_strike) is also a useful alias
        # after stripping the platform prefix and the underscore convention.
        if "." in family_key:
            stripped = family_key.split(".", 1)[1].replace("_", " ")
            if stripped:
                all_aliases.append(stripped)

        seen: set[str] = set()
        unique = []
        for a in all_aliases:
            key = _normalize_alias(a)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(a)

        record = {
            "canonical": common_name,
            "mitre_software_id": mitre_software_id,
            "platforms": [platform] if platform else [],
            "actors": list(attribution),
            "aliases": unique,
        }

        for alias in unique:
            key = _normalize_alias(alias)
            if not key:
                continue
            existing = families.get(key)
            if existing is None:
                families[key] = record
            elif mitre_software_id and not existing.get("mitre_software_id"):
                families[key] = record

    print(f"  families: {len(raw)} canonical, {len(families)} alias keys")
    return families


def main() -> int:
    actors_raw = json.loads(_http_get(ACTORS_URL))
    families_raw = json.loads(_http_get(FAMILIES_URL))

    print("\nBuilding lookups ...")
    actors = build_actors(actors_raw)
    families = build_families(families_raw)

    out = {
        "version": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source": "https://malpedia.caad.fkie.fraunhofer.de/",
        "license": "CC BY-NC-SA 4.0",
        "stats": {
            "actor_canonical": len(actors_raw),
            "actor_aliases": len(actors),
            "family_canonical": len(families_raw),
            "family_aliases": len(families),
        },
        "actors": actors,
        "families": families,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"Wrote {OUT}")
    print(f"  size: {OUT.stat().st_size / 1024:.1f} KB")
    print(f"  actor aliases:  {len(actors)}")
    print(f"  family aliases: {len(families)}")

    # Spot-check a few well-known actors so we can verify the pipeline works.
    print("\nSpot checks:")
    for q in ["apt29", "midnight blizzard", "volt typhoon", "bronze silhouette",
              "lazarus group", "cobalt strike", "mimikatz"]:
        key = _normalize_alias(q)
        rec = actors.get(key) or families.get(key)
        kind = "actor" if key in actors else "family" if key in families else None
        if rec and kind == "actor":
            print(
                f"  {q!r:>22} -> {rec['canonical']!r}, "
                f"mitre_group={rec.get('mitre_group_id')}, country={rec.get('country')}"
            )
        elif rec and kind == "family":
            print(
                f"  {q!r:>22} -> {rec['canonical']!r}, "
                f"mitre_software={rec.get('mitre_software_id')}"
            )
        else:
            print(f"  {q!r:>22} -> NOT FOUND")
    return 0


if __name__ == "__main__":
    sys.exit(main())
