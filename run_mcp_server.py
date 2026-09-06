#!/usr/bin/env python3
"""Step 5 access point 3 — MCP server for OpenClaw.

Unlike run_server.py (Open WebUI, local to this machine), this binds to the LAN
interface by default (config: mcp_host, default 0.0.0.0) since OpenClaw runs on a
separate VM (npabot-u24) and needs to reach this over the network.

Usage:
    ./run_mcp_server.py [--config config/query_config.yaml]

Add to OpenClaw's config (npabot-u24) once running:
    mcp: {
      servers: {
        "hybrid-rag": {
          url: "http://<this-desktop-LAN-IP>:8200/mcp",
          transport: "streamable-http",
          enabled: true,
        },
      },
    }
"""
from __future__ import annotations

import argparse

from query.config import QueryConfig
from query.logging_setup import setup_query_logging
from query.mcp_server import create_mcp_server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/query_config.yaml", help="Path to query_config.yaml")
    args = parser.parse_args()

    config = QueryConfig.load(args.config)
    log_path = setup_query_logging(config.logs_dir)
    print(f"Log: {log_path}")
    print(f"MCP server listening on http://{config.mcp_host}:{config.mcp_port}/mcp")
    print("Add this to OpenClaw's mcp.servers config with the desktop's LAN IP.")

    server = create_mcp_server(config)
    server.run(transport="streamable-http", host=config.mcp_host, port=config.mcp_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
