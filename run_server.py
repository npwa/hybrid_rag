#!/usr/bin/env python3
"""Step 5 access points 2 & 3 — OpenAI-compatible HTTP server.

Open WebUI (§4) adds this as a custom model under Settings -> Connections.
OpenClaw/Signal (§5) is proposed to call this same endpoint, pending confirmation of
OpenClaw's actual tool-calling interface.

Usage:
    ./run_server.py [--config config/query_config.yaml]
"""
from __future__ import annotations

import argparse

import uvicorn

from query.config import QueryConfig
from query.logging_setup import setup_query_logging
from query.server import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/query_config.yaml", help="Path to query_config.yaml")
    args = parser.parse_args()

    config = QueryConfig.load(args.config)
    log_path = setup_query_logging(config.logs_dir)
    print(f"Log: {log_path}")
    print(f"Serving on http://{config.http_host}:{config.http_port}  (model id: hybrid-rag)")

    app = create_app(config)
    uvicorn.run(app, host=config.http_host, port=config.http_port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
