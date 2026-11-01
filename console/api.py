"""The console API (requirements section 5): read-only, side-effect free, JSON errors (API4).
Created per config so tests and demo mode can point it at any data root."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta

from fastapi import FastAPI, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from console import __version__
from console.config import ConsoleConfig
from console.health import build_health
from console.failures import CAUSES
from console import queries as queries_mod
from console import gold as gold_mod
from console import runbooks
from console.readers import agent_log, maintenance_log, query_log
from console.readers.lance_reader import LanceReadOnly
from console.readers.sqlite_ro import FAILURE_SORTS, failures as failures_query, open_ro, summary as summary_query

log = logging.getLogger("console")

_PLACEHOLDER = """<!doctype html><meta charset="utf-8"><title>Hybrid RAG console</title>
<body style="font:16px system-ui;margin:2rem"><h1>Hybrid RAG console</h1>
<p>The API is running, the web UI is not built yet.</p>
<p>See <a href="/docs">/docs</a> for the API and <a href="/api/v1/health">/api/v1/health</a> for status.</p></body>"""


class ExploreRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000, description="the question to explore")
    generate: bool = Field(False, description="also generate an answer with the language model (uses the GPU)")


def _host_name(header: str) -> str:
    """'localhost:8300' -> 'localhost'; '[::1]:8300' -> '::1'."""
    if header.startswith("["):
        return header[1:].split("]", 1)[0]
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


def create_app(config: ConsoleConfig, embed=None, query_config=None) -> FastAPI:
    """`embed` / `query_config` are test hooks; the explorer builds both itself otherwise."""
    def _warm_up():   # importing lancedb takes ~0.9 s; do it before the first request needs it (API3: under 1 s)
        try:
            import lancedb  # noqa: F401
        except Exception:
            pass
    threading.Thread(target=_warm_up, daemon=True).start()

    app = FastAPI(title="Hybrid RAG console", version=__version__,
                  description="Read-only observability API for the Hybrid RAG pipeline.")

    loopback_only = config.host in ("127.0.0.1", "localhost", "::1")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # DNS-rebinding defence: a web page on another site can make the browser send requests to
        # 127.0.0.1 with the attacker's host name. Only loopback names are served when bound to loopback.
        if loopback_only:
            host = _host_name(request.headers.get("host", ""))
            if host not in ("127.0.0.1", "localhost", "::1"):
                return JSONResponse(status_code=421, content={"error": "bad_host", "detail": "use http://127.0.0.1 or http://localhost"})
        # The only non-GET route is the explorer, a POST because the question can be long; it only reads.
        if request.method not in ("GET", "HEAD") and (request.method, request.url.path) != ("POST", "/api/v1/explore"):
            return JSONResponse(status_code=405, content={"error": "read_only", "detail": "the console is read-only"},
                                headers={"Allow": "GET, HEAD"})
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                   "img-src 'self' data:; frame-ancestors 'none'")
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": "internal_error", "detail": type(exc).__name__})

    @app.get("/api/v1/health", summary="Status header data and read-only proof")
    def health():
        return build_health(config)

    def _unavailable(detail: str):
        return JSONResponse(status_code=503, content={"error": "source_unavailable", "detail": detail})

    @app.get("/api/v1/index/summary", summary="Files and chunks by status, outcome, type and failure cause")
    def index_summary():
        if not config.manifest_db.exists():
            return _unavailable(f"manifest not found: {config.manifest_db}")
        conn = open_ro(config.manifest_db)
        try:
            data = summary_query(conn)
        finally:
            conn.close()
        chunks, ann = data["chunks_total"], None
        try:
            ann = LanceReadOnly(config.lancedb_dir, config.lancedb_table).has_ann_index()
        except Exception:
            pass
        threshold = config.ann_threshold_chunks
        state = "needs_index" if chunks >= threshold else "approaching" if chunks >= threshold // 2 else "ok"
        if ann:
            state = "indexed"
        data["ann"] = {"chunks": chunks, "threshold": threshold, "percent_of_threshold": round(100 * chunks / threshold, 1),
                       "has_ann_index": ann, "state": state, "ticket": "HYR-02"}
        data["ann_threshold_chunks"] = threshold
        return data

    @app.get("/api/v1/index/failures", summary="Problem files with cause category (filter, sort, paginate)")
    def index_failures(cause: str | None = Query(None, description="one of " + ", ".join(CAUSES)),
                       extension: str | None = None, status: str | None = None, q: str | None = Query(None, description="substring of the path"),
                       sort: str = Query("path", pattern="^(" + "|".join(list(FAILURE_SORTS) + ["cause"]) + ")$"),
                       desc: bool = False, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        if cause is not None and cause not in CAUSES:
            return JSONResponse(status_code=422, content={"error": "bad_request", "detail": f"unknown cause '{cause}'"})
        if not config.manifest_db.exists():
            return _unavailable(f"manifest not found: {config.manifest_db}")
        conn = open_ro(config.manifest_db)
        try:
            return failures_query(conn, cause=cause, extension=extension, status=status, q=q, sort=sort, desc=desc,
                                  limit=limit, offset=offset, mask=config.mask_queries)
        finally:
            conn.close()

    @app.get("/api/v1/index/causes", summary="Failure cause categories with labels and ticket ids")
    def index_causes():
        from console.failures import cause_info
        return [cause_info(c) for c in CAUSES]

    @app.get("/api/v1/maintenance/runs", summary="Maintenance run history (newest first)")
    def maintenance_runs(limit: int = Query(30, ge=1, le=500)):
        runs = maintenance_log.read_runs(config.logs_dir / "maintenance.log")
        return {"total": len(runs), "items": [
            {"started": r.started, "ended": r.ended, "result": r.result, "seconds": r.seconds,
             "added": r.added, "changed": r.changed, "removed": r.removed, "stages": r.stages,
             "index_ok_at": r.index_ok_at} for r in reversed(runs)][:limit]}

    @app.post("/api/v1/explore", summary="How retrieval reached its ranking for one question (no side effects on production logs)")
    def explore_query(req: ExploreRequest):
        from console import explorer          # lazy: loads the query engine only when the explorer is used
        query = req.query.strip()
        if not query:
            return JSONResponse(status_code=422, content={"error": "bad_request", "detail": "query is empty"})
        if not config.demo and not (config.manifest_db.exists() and config.lancedb_dir.exists()):
            return _unavailable("manifest or vector index not found")
        try:
            return explorer.explore(config, query, generate=req.generate, embed=embed, qcfg=query_config)
        except explorer.Busy:
            return JSONResponse(status_code=429, content={"error": "busy", "detail": "another exploration is running; try again"})
        except Exception as e:
            from indexing.embedder import EmbeddingError
            if isinstance(e, EmbeddingError):
                return JSONResponse(status_code=502, content={"error": "embedding_failed", "detail": str(e)})
            raise

    @app.get("/api/v1/toolcalls/summary", summary="Agent tool-call activity from OpenClaw logs, reconciled with desktop MCP calls")
    def toolcalls_summary(days: int = Query(30, ge=1, le=365)):
        now = config.now()
        events, files = agent_log.read_dir(config.agent_logs_dir)
        summary_file = config.agent_logs_dir / "config-summary.json"
        agent_cfg = None
        if summary_file.exists():
            try:
                agent_cfg = json.loads(summary_file.read_text())
            except (OSError, json.JSONDecodeError):
                agent_cfg = None
        newest = max((f.stat().st_mtime for f in files), default=None)
        age = None if newest is None else round((now.timestamp() - newest) / 3600, 1)
        if config.demo and events:
            age = round((now - events[-1].ts).total_seconds() / 3600, 1)      # demo files carry the generation time, not the demo clock
        sources = {"files": len(files), "newest_file": files[-1].name if files else None,
                   "age_hours": age,
                   "agent_logs_dir": str(config.agent_logs_dir),
                   "config_summary": agent_cfg, "pull_script": "scripts/pull_agent_logs.sh"}
        warnings = []
        if files and age is not None and age > 36:
            warnings.append({"id": "agent_logs_stale", "text": f"The newest copied log is {age:.0f} h old.", "runbook": runbooks.runbook_path("agent_logs_stale")})
        if not files:
            return {"available": False, "sources": sources, "warnings": [{"id": "agent_logs_missing", "text": "No OpenClaw logs copied yet.",
                                                                          "runbook": runbooks.runbook_path("agent_logs_missing")}],
                    "detail": "No OpenClaw logs found. Run scripts/pull_agent_logs.sh to copy them from the bot VM."}
        qev = []
        for i in range(days + 1):
            qev += query_log.read_day(config.logs_dir, (now.date() - timedelta(days=i)).isoformat())
        calls = agent_log.mcp_calls_from_events(qev)
        result = agent_log.analyze(events, calls, days=days, now=now,
                                   fallback_model=(agent_cfg or {}).get("primary_model"))
        for f in result["flags"]:
            f["runbook"] = runbooks.runbook_path(f["kind"])
        return {"available": True, "sources": sources, "warnings": warnings, "jsonl_days_with_mcp_records": sum(
                    1 for i in range(days + 1) if (config.logs_dir / f"query_{(now.date() - timedelta(days=i)).isoformat()}.jsonl").exists()),
                **result}

    @app.get("/api/v1/gold", summary="Result of the last gold question set run (scripts/run_gold_set.py --save-report)")
    def gold_report():
        rep = gold_mod.load_report(config.logs_dir)
        if rep is None:
            return {"available": False, "detail": "No gold set run saved yet. Run scripts/run_gold_set.py --save-report (see the console guide)."}
        from console.failures import mask_path, mask_text
        mask = config.mask_queries
        saved = (config.logs_dir / gold_mod.REPORT_NAME).stat().st_mtime
        items = [{**{k: r[k] for k in ("id", "expect", "verdict", "passed", "problems", "hits", "nearest_distance", "first_expected_rank", "within")},
                  "question": mask_text(r["question"]) if mask else r["question"],
                  "sources_any": [] if mask else r.get("sources_any", []),
                  "top_sources": [mask_path(x) for x in r["top_sources"]] if mask else r["top_sources"]} for r in rep["results"]]
        return {"available": True, "masked": mask, "saved_at": datetime.fromtimestamp(saved).strftime("%Y-%m-%dT%H:%M:%S"),
                "settings": rep["settings"], "overrides": rep.get("overrides", []), "total": rep["total"], "passed": rep["passed"],
                "failed": rep["failed"], "compared_with": rep.get("compared_with"), "items": items}

    @app.get("/api/v1/runbooks", summary="Every warning the console can show and the runbook that explains it")
    def runbook_index():
        return runbooks.listing()

    @app.get("/api/v1/queries/stats", summary="Query log aggregates: volume, latency, outcome rates, recurring questions")
    def queries_stats(days: int = Query(30, ge=1, le=365), slow_seconds: float | None = Query(None, gt=0, description="override the configured slow threshold")):
        return queries_mod.stats(config, days, slow_seconds)

    @app.get("/api/v1/queries/slow", summary="Slowest queries, queries with no relevant result, or failed queries")
    def queries_slow(days: int = Query(30, ge=1, le=365), kind: str = Query("slow", pattern="^(slow|no_result|error)$"),
                     limit: int = Query(20, ge=1, le=200), slow_seconds: float | None = Query(None, gt=0)):
        return queries_mod.listing(config, days, kind, limit, slow_seconds)

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
