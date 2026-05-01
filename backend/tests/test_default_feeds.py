"""Tests for the curated feed catalog and seeding flow."""
from __future__ import annotations


def test_catalog_loads_and_has_expected_categories():
    from pharos.feeds import load_catalog

    cat = load_catalog()
    cat_ids = {c.id for c in cat.categories}
    assert {"government", "vendors", "news", "research", "twitter"} <= cat_ids

    # The Twitter category should not be enabled by default.
    twitter = cat.category("twitter")
    assert twitter is not None
    assert twitter.enabled_by_default is False

    # Every other category should be enabled by default.
    for cid in ("government", "vendors", "news", "research"):
        c = cat.category(cid)
        assert c is not None and c.enabled_by_default is True

    # A handful of must-have feeds should be present.
    gov_urls = {f.url for f in cat.category("government").feeds}
    assert any("cisa.gov" in u for u in gov_urls)
    vendor_urls = {f.url for f in cat.category("vendors").feeds}
    assert any("talosintelligence.com" in u for u in vendor_urls)
    assert any("paloaltonetworks.com" in u for u in vendor_urls)


def test_presets_include_starter_and_everything():
    from pharos.feeds import load_catalog

    cat = load_catalog()
    pids = {p.id for p in cat.presets}
    assert {"starter", "minimal", "full", "everything"} <= pids
    assert cat.preset("starter").categories == ["government", "vendors", "news"]


def test_seed_user_is_idempotent_and_subscribes(tmp_db_dir):
    from pharos.api.auth import create_user
    from pharos.db import connect, init_databases
    from pharos.feeds import seed_user

    init_databases()
    with connect(attach_cold=False) as conn:
        create_user(conn, username="alice", password="hunter22", is_admin=True)
        conn.commit()

    r1 = seed_user(username="alice", category_ids=["government"])
    assert r1.added_subscriptions > 0
    assert r1.skipped_existing == 0

    # Re-running adds nothing new.
    r2 = seed_user(username="alice", category_ids=["government"])
    assert r2.added_subscriptions == 0
    assert r2.skipped_existing == r1.added_subscriptions

    # Subscriptions actually exist.
    with connect(attach_cold=False) as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM subscriptions s "
            "JOIN users u ON u.id = s.user_id WHERE u.username = ?",
            ("alice",),
        ).fetchone()["c"]
    assert n == r1.added_subscriptions


def test_seed_with_preset(tmp_db_dir):
    from pharos.api.auth import create_user
    from pharos.db import connect, init_databases
    from pharos.feeds import load_catalog, seed_user

    init_databases()
    with connect(attach_cold=False) as conn:
        create_user(conn, username="bob", password="x", is_admin=False)
        conn.commit()

    catalog = load_catalog()
    expected = sum(
        len(catalog.category(cid).feeds)
        for cid in catalog.preset("starter").categories
    )

    r = seed_user(username="bob", preset_id="starter")
    assert r.added_subscriptions == expected


def test_seed_unknown_preset_raises(tmp_db_dir):
    import pytest

    from pharos.api.auth import create_user
    from pharos.db import connect, init_databases
    from pharos.feeds import seed_user

    init_databases()
    with connect(attach_cold=False) as conn:
        create_user(conn, username="cara", password="x")
        conn.commit()

    with pytest.raises(ValueError):
        seed_user(username="cara", preset_id="does-not-exist")
