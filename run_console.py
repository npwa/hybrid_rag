#!/usr/bin/env python3
"""Step 9 - operator console (read-only API + web UI). See Doc/step-9-requirements.md.

Usage:
    ./run_console.py [--config config/console_config.yaml] [--demo] [--host H] [--port P]

--demo serves the synthetic dataset (scripts/make_synthetic_data.py) instead of real data.
Binds to 127.0.0.1 by default; binding anywhere else exposes personal data on the network.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from console.api import create_app
from console.config import ConsoleConfig

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def bind_warning(host: str) -> str | None:
    if host in LOOPBACK:
        return None
    return (f"WARNING: binding to {host} makes the console (and the personal data it shows) reachable "
            f"from the network. There is no authentication in v1.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/console_config.yaml")
    parser.add_argument("--demo", action="store_true", help="serve the synthetic demo dataset")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        fallback = Path("config/console_config.example.yaml")
        print(f"{cfg_path} not found; using {fallback}", file=sys.stderr)
        cfg_path = fallback
    config = ConsoleConfig.load(cfg_path, demo=args.demo)
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.demo and not config.manifest_db.exists():
        print(f"demo data not found at {config.working_dir}; run scripts/make_synthetic_data.py first", file=sys.stderr)
        return 1
    if (w := bind_warning(config.host)):
        print(w, file=sys.stderr)
    print(f"Console on http://{config.host}:{config.port}  data: {config.working_dir}  {'(demo)' if config.demo else ''}")
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
