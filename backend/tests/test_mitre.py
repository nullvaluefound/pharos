from pharos.lantern import mitre


def test_validators():
    assert mitre.is_group("G0016")
    assert not mitre.is_group("g16")
    assert mitre.is_software("S0154")
    assert mitre.is_technique("T1566")
    assert mitre.is_technique("T1566.001")
    assert not mitre.is_technique("T1566.")
    assert mitre.is_tactic("TA0001")


def test_parent_technique():
    assert mitre.parent_technique("T1566.001") == "T1566"
    assert mitre.parent_technique("T1566") == "T1566"


def test_attack_urls():
    assert mitre.attack_url("G0016") == "https://attack.mitre.org/groups/G0016/"
    assert mitre.attack_url("S0154") == "https://attack.mitre.org/software/S0154/"
    assert mitre.attack_url("T1566") == "https://attack.mitre.org/techniques/T1566/"
    assert mitre.attack_url("T1566.001") == \
        "https://attack.mitre.org/techniques/T1566/001/"
    assert mitre.attack_url("TA0001") == "https://attack.mitre.org/tactics/TA0001/"
    assert mitre.attack_url("nope") is None
