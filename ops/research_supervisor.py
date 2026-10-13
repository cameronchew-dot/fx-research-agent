#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.market_data import (  # noqa: E402
    market_data_status,
    register_manifest,
    sync_market_exports,
)
from fx_research_agent.registry import backlog, import_genesis, status  # noqa: E402
from fx_research_agent.storage import connect  # noqa: E402


DEFAULT_DB = ROOT / "data" / "fx_research_agent.sqlite3"
DEFAULT_GENESIS = ROOT / "config" / "genesis_hypotheses.json"
DEFAULT_MARKET_SOURCE = Path("/Users/camcam/eur_bot/exports/fx_research")
DEFAULT_MARKET_INBOX = ROOT / "data" / "inbox"
DEFAULT_MARKET_SYNC_STATUS = ROOT / "data" / "market_ingest_status.json"
DEFAULT_MARKET_DATA_STATUS = ROOT / "data" / "market_data_status.json"
SOURCE_REPO = "https://github.com/cameronchew-dot/eur-usd-agent.git"
SOURCE_COMMIT = "e168603"
SOURCE_PATH = "config/research_hypothesis_registry.json"


def print_json(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


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
    sync = commands.add_parser("sync-market-exports")
    sync.add_argument("--source-dir", type=Path, default=DEFAULT_MARKET_SOURCE)
    sync.add_argument("--inbox-dir", type=Path, default=DEFAULT_MARKET_INBOX)
    commands.add_parser("market-data-status")
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
        elif args.command == "sync-market-exports":
            result = sync_market_exports(connection, args.source_dir, args.inbox_dir)
            quality = market_data_status(connection)
            write_json_atomic(DEFAULT_MARKET_SYNC_STATUS, result)
            write_json_atomic(DEFAULT_MARKET_DATA_STATUS, quality)
            print_json({"sync": result, "quality": quality})
        elif args.command == "market-data-status":
            result = market_data_status(connection)
            write_json_atomic(DEFAULT_MARKET_DATA_STATUS, result)
            print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

