"""Centralized configuration loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o")
    openai_base_url: str | None = Field(default=None)
    # When set to a comma-separated list (e.g. "web_search_preview"), the
    # lantern attaches those OpenAI tools to every enrichment call so the
    # model can verify novel actor / malware attributions against current
    # sources. Off by default because it ~3x's the per-call cost.
    openai_tools: str = Field(default="")

    # Storage
    pharos_db_dir: Path = Field(default=Path("./data"))

    # Retention
    # Keep roughly one quarter of articles in the hot DB for fast browsing.
    # Older articles (and their tokens / entity links) are moved to cold.db
    # by the archiver but remain searchable via the Archive Search page.
    archive_after_days: int = Field(default=90, ge=1)

    # Constellations
    cluster_window_days: int = Field(default=7, ge=1)
    cluster_min_shared: int = Field(default=4, ge=1)
    cluster_sim_threshold: float = Field(default=0.55, ge=0.0, le=1.0)

    # Lantern
    lantern_batch: int = Field(default=10, ge=1)
    lantern_concurrency: int = Field(default=4, ge=1)
    lantern_poll_interval_sec: int = Field(default=10, ge=1)

    # Ingestion
    default_feed_poll_interval_sec: int = Field(default=900, ge=30)
    http_user_agent: str = Field(default="Pharos/0.1")

    # API
    jwt_secret: str = Field(default="dev-secret-change-me")
    jwt_algorithm: str = Field(default="HS256")
    jwt_ttl_seconds: int = Field(default=60 * 60 * 24 * 7)
    allow_registration: bool = Field(default=False)
    cors_origins: str = Field(default="http://localhost:3000")

    # When deployed behind a reverse-proxy at a sub-path (e.g. nginx
    # proxying /pharos/api/ -> uvicorn), set this to "/pharos" so OpenAPI
    # links and redirects know the public prefix.
    root_path: str = Field(default="")

    # Logging
    log_level: str = Field(default="INFO")

    @property
    def hot_db_path(self) -> Path:
        return self.pharos_db_dir / "hot.db"

    @property
    def cold_db_path(self) -> Path:
        return self.pharos_db_dir / "cold.db"

    @property
    def blobs_dir(self) -> Path:
        return self.pharos_db_dir / "blobs"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.pharos_db_dir.mkdir(parents=True, exist_ok=True)
    s.blobs_dir.mkdir(parents=True, exist_ok=True)
    return s
