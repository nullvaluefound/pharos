"""Shared test fixtures: isolated databases per test."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_db_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="pharos-test-"))
    monkeypatch.setenv("PHAROS_DB_DIR", str(tmpdir))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    # Bust the cached settings so the new env vars take effect.
    from pharos import config
    config.get_settings.cache_clear()
    return tmpdir
