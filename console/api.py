"""The console API (requirements section 5): read-only, side-effect free, JSON errors (API4).
Created per config so tests and demo mode can point it at any data root."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from console import __version__
from console.config import ConsoleConfig
from console.health import build_health
from console.readers.sqlite_ro import index_counts, open_ro

log = logging.getLogger("console")

_PLACEHOLDER = """<!doctype html><meta charset="utf-8"><title>Hybrid RAG console</title>
<body style="font:16px system-ui;margin:2rem"><h1>Hybrid RAG console</h1>
<p>The API is running, the web UI is not built yet.</p>
<p>See <a href="/docs">/docs</a> for the API and <a href="/api/v1/health">/api/v1/health</a> for status.</p></body>"""


def create_app(config: ConsoleConfig) -> FastAPI:
    app = FastAPI(title="Hybrid RAG console", version=__version__,
                  description="Read-only observability API for the Hybrid RAG pipeline.")

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": "internal_error", "detail": type(exc).__name__})

    @app.get("/api/v1/health", summary="Status header data and read-only proof")
    def health():
        return build_health(config)

    @app.get("/api/v1/index/summary", summary="Counts of files and chunks by status")
    def index_summary():
        if not config.manifest_db.exists():
            return JSONResponse(status_code=503, content={
                "error": "source_unavailable", "detail": f"manifest not found: {config.manifest_db}"})
        conn = open_ro(config.manifest_db)
        try:
            counts = index_counts(conn)
        finally:
            conn.close()
        return {**counts, "ann_threshold_chunks": config.ann_threshold_chunks}

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=404, content={"error": "not_found", "detail": request.url.path})
        return HTMLResponse(_PLACEHOLDER, status_code=404)

    if config.static_dir.is_dir() and (config.static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(config.static_dir), html=True), name="web")
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def root():
            return _PLACEHOLDER

    return app
