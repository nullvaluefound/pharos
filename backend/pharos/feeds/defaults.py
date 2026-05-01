"""Curated default-feed catalog and seeding helpers.

The catalog ships as YAML at ``pharos/data/default_feeds.yaml``; this
module loads it into typed dataclasses and provides a ``seed_user()``
function that creates feed rows + subscriptions for a given user.

Usage:

    from pharos.feeds import load_catalog, seed_user

    cat = load_catalog()
    added = seed_user(username="alice", category_ids=["government", "news"])

The CLI (`pharos seed-feeds`) and the admin API (`POST /admin/seed-feeds`)
both wrap this module.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import resources

import yaml

from ..config import get_settings
from ..db import connect

log = logging.getLogger(__name__)


@dataclass(slots=True)
class FeedSpec:
    url: str
    title: str | None = None
    folder: str | None = None
    poll_interval_sec: int | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Category:
    id: str
    name: str
    folder: str
    description: str
    feeds: list[FeedSpec]
    enabled_by_default: bool = True


@dataclass(slots=True)
class Preset:
    id: str
    name: str
    description: str
    categories: list[str]


@dataclass(slots=True)
class Catalog:
    categories: list[Category]
    presets: list[Preset]

    def category(self, cat_id: str) -> Category | None:
        return next((c for c in self.categories if c.id == cat_id), None)

    def preset(self, preset_id: str) -> Preset | None:
        return next((p for p in self.presets if p.id == preset_id), None)


def _load_yaml() -> dict:
    text = resources.files("pharos.data").joinpath("default_feeds.yaml").read_text(
        encoding="utf-8"
    )
    return yaml.safe_load(text) or {}


def load_catalog() -> Catalog:
    """Parse the bundled YAML catalog into typed dataclasses."""
    raw = _load_yaml()
    categories: list[Category] = []
    for c in raw.get("categories", []):
        feeds = [
            FeedSpec(
                url=f["url"],
                title=f.get("title"),
                folder=f.get("folder"),
                poll_interval_sec=f.get("poll_interval_sec"),
                tags=list(f.get("tags", []) or []),
            )
            for f in c.get("feeds", [])
        ]
        categories.append(
            Category(
                id=c["id"],
                name=c["name"],
                folder=c.get("folder", ""),
                description=(c.get("description") or "").strip(),
                feeds=feeds,
                enabled_by_default=bool(c.get("enabled_by_default", True)),
            )
        )

    presets = [
        Preset(
            id=p["id"],
            name=p["name"],
            description=(p.get("description") or "").strip(),
            categories=list(p.get("categories", [])),
        )
        for p in raw.get("presets", [])
    ]
    return Catalog(categories=categories, presets=presets)


def _resolve_categories(
    catalog: Catalog,
    *,
    category_ids: list[str] | None = None,
    preset_id: str | None = None,
) -> list[Category]:
    """Pick the categories to apply, honoring an explicit list, a preset,
    or (failing both) the ``enabled_by_default`` flag on each category."""
    if category_ids:
        out: list[Category] = []
        for cid in category_ids:
            c = catalog.category(cid)
            if c is None:
                raise ValueError(f"Unknown category: {cid!r}")
            out.append(c)
        return out
    if preset_id:
        preset = catalog.preset(preset_id)
        if preset is None:
            raise ValueError(f"Unknown preset: {preset_id!r}")
        return [c for cid in preset.categories for c in [catalog.category(cid)] if c]
    return [c for c in catalog.categories if c.enabled_by_default]


@dataclass(slots=True)
class SeedResult:
    added_subscriptions: int
    skipped_existing: int
    new_feeds: int
    by_category: dict[str, int]


def seed_user(
    *,
    username: str,
    category_ids: list[str] | None = None,
    preset_id: str | None = None,
) -> SeedResult:
    """Subscribe ``username`` to every feed in the chosen categories.

    Idempotent: existing subscriptions are skipped, existing feeds are
    reused. Feeds new to the system are created with the user's
    configured default poll interval (or any per-feed override).
    """
    catalog = load_catalog()
    categories = _resolve_categories(
        catalog, category_ids=category_ids, preset_id=preset_id
    )

    settings = get_settings()
    result = SeedResult(0, 0, 0, {})

    with connect(attach_cold=False) as conn:
        urow = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not urow:
            raise ValueError(f"No such user: {username!r}")
        user_id = int(urow["id"])

        for cat in categories:
            per_cat = 0
            for spec in cat.feeds:
                interval = spec.poll_interval_sec or settings.default_feed_poll_interval_sec
                feed_row = conn.execute(
                    "SELECT id FROM feeds WHERE url = ?", (spec.url,)
                ).fetchone()
                if feed_row:
                    feed_id = int(feed_row["id"])
                else:
                    cur = conn.execute(
                        "INSERT INTO feeds (url, title, poll_interval_sec) "
                        "VALUES (?, ?, ?)",
                        (spec.url, spec.title, interval),
                    )
                    feed_id = int(cur.lastrowid)
                    result.new_feeds += 1

                existing = conn.execute(
                    "SELECT 1 FROM subscriptions WHERE user_id = ? AND feed_id = ?",
                    (user_id, feed_id),
                ).fetchone()
                if existing:
                    result.skipped_existing += 1
                    continue

                conn.execute(
                    "INSERT INTO subscriptions(user_id, feed_id, folder, custom_title) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, feed_id, spec.folder or cat.folder, spec.title),
                )
                result.added_subscriptions += 1
                per_cat += 1

            result.by_category[cat.id] = per_cat

    log.info(
        "seed_user(%s): added=%d, new_feeds=%d, skipped=%d",
        username,
        result.added_subscriptions,
        result.new_feeds,
        result.skipped_existing,
    )
    return result
