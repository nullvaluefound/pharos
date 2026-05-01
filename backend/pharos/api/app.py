"""FastAPI application factory."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings
from ..db import init_databases
from .routes import (
    admin,
    articles,
    auth,
    bookmarks,
    feeds,
    metrics,
    notifications,
    opml,
    reports,
    search,
    settings as settings_route,
    stream,
    watches,
)


def create_app() -> FastAPI:
    s = get_settings()
    logging.basicConfig(level=s.log_level)
    init_databases()

    app = FastAPI(
        title="Pharos",
        version="0.1.0",
        description="A self-hosted, open-source Feedly alternative.",
        root_path=s.root_path,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(feeds.router, prefix=api_prefix)
    app.include_router(stream.router, prefix=api_prefix)
    app.include_router(articles.router, prefix=api_prefix)
    app.include_router(search.router, prefix=api_prefix)
    app.include_router(bookmarks.router, prefix=api_prefix)
    app.include_router(watches.router, prefix=api_prefix)
    app.include_router(notifications.router, prefix=api_prefix)
    app.include_router(metrics.router, prefix=api_prefix)
    app.include_router(opml.router, prefix=api_prefix)
    app.include_router(settings_route.router, prefix=api_prefix)
    app.include_router(admin.router, prefix=api_prefix)
    app.include_router(reports.router, prefix=api_prefix)

    @app.get("/healthz", tags=["meta"])
    def health() -> dict:
        return {"ok": True, "name": "pharos", "version": "0.1.0"}

    return app
