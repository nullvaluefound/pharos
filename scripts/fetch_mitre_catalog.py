"""Fetch MITRE ATT&CK Enterprise catalog and write a compact JSON.

We pull the official STIX bundle from the MITRE/CTI GitHub repo and extract:

  - tactics       : list of {id, name}                 (TA####)
  - techniques    : list of {id, name, parent_id}      (T####, T####.###)

We DELIBERATELY do NOT include:
  - Groups (G####)   - per user request, the LLM should infer naming on
                       its own and we canonicalize against Malpedia after.
  - Software (S####) - the LLM has good malware-name recall already; the
                       catalog would just bloat the prompt.

The resulting file is committed to backend/pharos/lantern/data/mitre_catalog.json
so the runtime never depends on a network round-trip.

Run:  python scripts/fetch_mitre_catalog.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

STIX_URL = (
    "https://raw.githubusercontent.com/mitre/cti/master/"
    "enterprise-attack/enterprise-attack.json"
)

OUT = Path(__file__).resolve().parents[1] / "backend" / "pharos" / "lantern" / "data" / "mitre_catalog.json"


def fetch_stix() -> dict:
    print(f"Fetching {STIX_URL} ...", flush=True)
    req = urllib.request.Request(
        STIX_URL,
        headers={"User-Agent": "pharos-mitre-fetcher/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    print(f"  -> {len(data) / 1024 / 1024:.2f} MB")
    return json.loads(data)


def extract_id(obj: dict) -> str | None:
    """STIX objects store MITRE IDs as the value of an 'mitre-attack' external ref."""
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            return ref.get("external_id")
    return None


def build_catalog(bundle: dict) -> dict:
    tactics: list[dict] = []
    techniques: list[dict] = []

    # tactic short_name -> TA####
    tactic_shortname_to_id: dict[str, str] = {}

    # First pass: tactics
    for o in bundle.get("objects", []):
        if o.get("type") != "x-mitre-tactic" or o.get("revoked"):
            continue
        if o.get("x_mitre_deprecated"):
            continue
        ext_id = extract_id(o)
        if not ext_id or not ext_id.startswith("TA"):
            continue
        tactics.append({
            "id": ext_id,
            "name": o.get("name", "").strip(),
            "short_name": o.get("x_mitre_shortname", "").strip(),
        })
        if o.get("x_mitre_shortname"):
            tactic_shortname_to_id[o["x_mitre_shortname"]] = ext_id

    # ATT&CK doctrine ordering (Initial Access -> Impact)
    tactic_order = [
        "TA0043",  # Reconnaissance
        "TA0042",  # Resource Development
        "TA0001",  # Initial Access
        "TA0002",  # Execution
        "TA0003",  # Persistence
        "TA0004",  # Privilege Escalation
        "TA0005",  # Defense Evasion
        "TA0006",  # Credential Access
        "TA0007",  # Discovery
        "TA0008",  # Lateral Movement
        "TA0009",  # Collection
        "TA0011",  # Command and Control
        "TA0010",  # Exfiltration
        "TA0040",  # Impact
    ]
    tactics.sort(
        key=lambda t: (
            tactic_order.index(t["id"]) if t["id"] in tactic_order else 99,
            t["id"],
        )
    )

    # Second pass: techniques (and sub-techniques)
    for o in bundle.get("objects", []):
        if o.get("type") != "attack-pattern" or o.get("revoked"):
            continue
        if o.get("x_mitre_deprecated"):
            continue
        ext_id = extract_id(o)
        if not ext_id or not ext_id.startswith("T"):
            continue

        # Map tactic shortnames -> TA#### IDs via kill_chain_phases
        kc = o.get("kill_chain_phases", [])
        tactic_ids: list[str] = []
        for phase in kc:
            if phase.get("kill_chain_name") != "mitre-attack":
                continue
            short = phase.get("phase_name")
            tid = tactic_shortname_to_id.get(short)
            if tid:
                tactic_ids.append(tid)
        # de-dupe preserving order
        tactic_ids = list(dict.fromkeys(tactic_ids))

        parent_id = ext_id.split(".", 1)[0] if "." in ext_id else None

        techniques.append({
            "id": ext_id,
            "name": o.get("name", "").strip(),
            "parent_id": parent_id,
            "tactics": tactic_ids,
            "is_subtechnique": "." in ext_id,
        })

    # Sort: parents first, then sub-techniques under their parents.
    def tech_sort_key(t: dict) -> tuple:
        if "." in t["id"]:
            parent, sub = t["id"].split(".", 1)
            return (parent, int(sub))
        return (t["id"], -1)

    techniques.sort(key=tech_sort_key)

    return {
        "version": bundle.get("id", "unknown"),
        "fetched_from": STIX_URL,
        "stats": {
            "tactics": len(tactics),
            "techniques": len([t for t in techniques if not t["is_subtechnique"]]),
            "subtechniques": len([t for t in techniques if t["is_subtechnique"]]),
        },
        "tactics": tactics,
        "techniques": techniques,
    }


def main() -> int:
    bundle = fetch_stix()
    cat = build_catalog(bundle)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cat, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"Wrote {OUT}")
    print(f"  tactics:        {cat['stats']['tactics']}")
    print(f"  techniques:     {cat['stats']['techniques']}")
    print(f"  sub-techniques: {cat['stats']['subtechniques']}")
    print(f"  file size:      {OUT.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
