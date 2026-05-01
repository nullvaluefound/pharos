from pharos.lantern.constellations import shared_tokens, weighted_jaccard
from pharos.lantern.fingerprint import build_fingerprint
from pharos.lantern.schema import (
    CompanyEntity,
    EnrichedArticle,
    Entities,
    MalwareEntity,
    NamedEntity,
    ThreatActorEntity,
)


def make_article(
    *,
    actors: list[ThreatActorEntity] | None = None,
    cves: list[str] = (),
    companies: list[str] = (),
    products: list[str] = (),
    key_points: list[str] = (),
    malware: list[MalwareEntity] | None = None,
    mitre_groups: list[str] = (),
    ttps: list[str] = (),
) -> EnrichedArticle:
    return EnrichedArticle(
        overview="x",
        entities=Entities(
            threat_actors=actors or [],
            malware=malware or [],
            cves=list(cves),
            companies=[CompanyEntity(name=n) for n in companies],
            products=[NamedEntity(name=n) for n in products],
            mitre_groups=list(mitre_groups),
            ttps_mitre=list(ttps),
        ),
        key_points=list(key_points),
    )


def test_fingerprint_is_deterministic_and_namespaced():
    a = make_article(
        actors=[ThreatActorEntity(name="APT29", mitre_group_id="G0016")],
        cves=["CVE-2024-12345"],
        companies=["Microsoft"],
        ttps=["T1566.001"],
    )
    fp1 = build_fingerprint(a, title="APT29 exploits Microsoft Exchange")
    fp2 = build_fingerprint(a, title="APT29 exploits Microsoft Exchange")
    assert fp1 == fp2
    assert "thr:apt29" in fp1
    assert "mtg:g0016" in fp1                 # MITRE Group ID
    assert "cve:cve-2024-12345" in fp1
    assert "ttp:t1566.001" in fp1
    assert "ttp:t1566" in fp1                 # parent technique also added
    assert "com:microsoft" in fp1


def test_weighted_jaccard_prefers_high_signal_overlap():
    base = make_article(
        actors=[ThreatActorEntity(name="APT29", mitre_group_id="G0016")],
        cves=["CVE-2024-12345"],
        companies=["Microsoft"],
    )
    near = make_article(
        actors=[ThreatActorEntity(name="APT29", mitre_group_id="G0016")],
        cves=["CVE-2024-12345"],
        companies=["Microsoft"],
    )
    far = make_article(
        actors=[ThreatActorEntity(name="Lazarus", mitre_group_id="G0032")],
        companies=["Acme"],
    )
    a = set(build_fingerprint(base, title="APT29 exchange exploit"))
    b = set(build_fingerprint(near, title="Russian hackers Exchange flaw"))
    c = set(build_fingerprint(far, title="Lazarus targets Acme"))
    sim_near = weighted_jaccard(a, b)
    sim_far = weighted_jaccard(a, c)
    assert sim_near > sim_far
    assert sim_near > 0.4


def test_shared_tokens_orders_by_weight_desc():
    a = {"cve:cve-1", "thr:apt29", "w:exchange"}
    b = {"cve:cve-1", "thr:apt29", "w:exchange", "w:other"}
    out = shared_tokens(a, b)
    assert out[0].startswith("cve:")
    assert "w:exchange" in out


def test_invalid_mitre_group_id_rejected():
    import pytest

    with pytest.raises(ValueError):
        ThreatActorEntity(name="APT29", mitre_group_id="not-a-group")


def test_invalid_technique_id_rejected():
    import pytest

    with pytest.raises(ValueError):
        Entities(ttps_mitre=["NOT-A-TECHNIQUE"])


def test_cve_normalization():
    e = Entities(cves=["cve-2024-12345", "garbage", "CVE-2023-1"])
    # garbage and CVE-2023-1 (only 1 digit) dropped; valid one normalized
    assert e.cves == ["CVE-2024-12345"]
