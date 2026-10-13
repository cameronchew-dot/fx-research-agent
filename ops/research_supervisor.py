#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.market_data import register_manifest  # noqa: E402
from fx_research_agent.registry import backlog, import_genesis, status  # noqa: E402
from fx_research_agent.storage import connect  # noqa: E402


DEFAULT_DB = ROOT / "data" / "fx_research_agent.sqlite3"
DEFAULT_GENESIS = ROOT / "config" / "genesis_hypotheses.json"
SOURCE_REPO = "https://github.com/cameronchew-dot/eur-usd-agent.git"
SOURCE_COMMIT = "e168603"
SOURCE_PATH = "config/research_hypothesis_registry.json"


def print_json(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="FX research system-of-record supervisor")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    commands.add_parser("import-genesis")
    commands.add_parser("status")
    commands.add_parser("backlog")
    market = commands.add_parser("register-market-export")
    market.add_argument("manifest", type=Path)
    args = parser.parse_args()

    with connect(args.db) as connection:
        if args.command == "init-db":
            print_json(status(connection))
        elif args.command == "import-genesis":
            print_json(
                import_genesis(
                    connection,
                    DEFAULT_GENESIS,
                    SOURCE_REPO,
                    SOURCE_COMMIT,
                    SOURCE_PATH,
                )
            )
        elif args.command == "status":
            print_json(status(connection))
        elif args.command == "backlog":
            print_json(backlog(connection))
        elif args.command == "register-market-export":
            print_json(register_manifest(connection, args.manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

