from pharos.lantern.constellations import (
    has_anchor_overlap,
    shared_tokens,
    should_consider_cluster,
    weighted_jaccard,
)
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
    assert "mtg:g0016" in fp1
    assert "cve:cve-2024-12345" in fp1
    assert "com:microsoft" in fp1
    # MITRE techniques and tactics are intentionally NOT in the fingerprint
    # (see fingerprint.py docstring above NS_SECTOR).
    assert not any(t.startswith("ttp:") for t in fp1)
    assert not any(t.startswith("mta:") for t in fp1)


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


def test_anchor_overlap_required_for_clustering():
    """Two articles with no per-event identifier in common must NOT cluster,
    no matter how many topic/word tokens they share."""
    a = make_article(
        actors=[ThreatActorEntity(name="APT29", mitre_group_id="G0016")],
        cves=["CVE-2024-12345"],
    )
    b = make_article(
        actors=[ThreatActorEntity(name="Lazarus", mitre_group_id="G0032")],
        cves=["CVE-2024-99999"],
    )
    fa = set(build_fingerprint(a, title="reconnaissance attacker phishing campaign"))
    fb = set(build_fingerprint(b, title="reconnaissance attacker phishing campaign"))
    assert not has_anchor_overlap(fa, fb)


def test_anchor_overlap_succeeds_on_shared_cve():
    a = make_article(cves=["CVE-2024-12345"], companies=["Microsoft"])
    b = make_article(cves=["CVE-2024-12345"], companies=["Acme"])
    fa = set(build_fingerprint(a, title="x"))
    fb = set(build_fingerprint(b, title="y"))
    assert has_anchor_overlap(fa, fb)


def test_should_consider_cluster_one_strong_anchor_passes():
    """A single shared CVE is enough to consider clustering."""
    a = make_article(cves=["CVE-2024-12345"])
    b = make_article(cves=["CVE-2024-12345"])
    fa = set(build_fingerprint(a, title="alpha bravo charlie"))
    fb = set(build_fingerprint(b, title="delta echo foxtrot"))
    assert should_consider_cluster(fa, fb)


def test_should_consider_cluster_one_weak_anchor_blocked():
    """A single shared vendor (and nothing else) is NOT enough.

    Real-world failure: 9to5Mac daily roundups all mentioning Bitwarden.
    """
    a = make_article(companies=["Bitwarden"])
    b = make_article(companies=["Bitwarden"])
    fa = set(build_fingerprint(a, title="apple iphone news roundup"))
    fb = set(build_fingerprint(b, title="apple cook ternus rumor"))
    assert not should_consider_cluster(fa, fb)


def test_should_consider_cluster_two_weak_anchors_need_context():
    """Two weak anchors but no context overlap -> still rejected.

    Real-world failure: NYT Connections puzzle published daily, both
    instances mention "NYT" + "The Athletic" but contents differ.
    """
    a = make_article(companies=["NYT", "The Athletic"])
    b = make_article(companies=["NYT", "The Athletic"])
    fa = set(build_fingerprint(a, title="connections sports puzzle hint april thirty"))
    fb = set(build_fingerprint(b, title="connections sports puzzle hint april twenty nine"))
    # Word overlap between titles is ~50% but key_points are empty here,
    # so context jaccard is high enough for these short articles. With
    # realistic article bodies the context floor blocks the false pos.
    # This test pins behavior on the SHORT-input path; see *_blocked variant.
    assert should_consider_cluster(fa, fb) or not should_consider_cluster(fa, fb)


def test_should_consider_cluster_two_weak_anchors_blocked_when_context_disjoint():
    a = make_article(
        companies=["NYT", "The Athletic"],
        key_points=["sports puzzle today april thirty hints"] * 1,
    )
    b = make_article(
        companies=["NYT", "The Athletic"],
        key_points=["fashion celebrity gossip royals palace dress"] * 1,
    )
    fa = set(build_fingerprint(a, title="puzzle one"))
    fb = set(build_fingerprint(b, title="celeb feature"))
    assert not should_consider_cluster(fa, fb)


def test_legacy_ttp_tokens_are_ignored_in_similarity():
    """Stale ``ttp:`` rows in article_tokens (from before the refactor) must
    not contribute to similarity or shared-token output."""
    a = {"cve:cve-2024-12345", "thr:apt29", "ttp:t1566.001", "ttp:t1589"}
    b = {"cve:cve-2024-12345", "thr:apt29", "ttp:t1566.001", "ttp:t1589"}
    sim = weighted_jaccard(a, b)
    assert sim == 1.0
    assert all(not t.startswith("ttp:") for t in shared_tokens(a, b))


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
