#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fx_research_agent.databento_continuous import build_product
from fx_research_agent.market_data import register_manifest
from fx_research_agent.storage import connect


def main() -> int:
    parser = argparse.ArgumentParser(description="Build causal CME FX continuous-contract datasets")
    parser.add_argument("--product", choices=["all", "6E", "6J", "6A"], default="all")
    parser.add_argument(
        "--package-root", type=Path, default=ROOT / "data" / "external" / "databento"
    )
    parser.add_argument(
        "--output-root", type=Path, default=ROOT / "data" / "derived" / "databento_continuous"
    )
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "fx_research_agent.sqlite3")
    args = parser.parse_args()
    products = ["6E", "6J", "6A"] if args.product == "all" else [args.product]
    results = [build_product(args.package_root, args.output_root, product) for product in products]
    if args.register:
        connection = connect(args.db)
        try:
            for result in results:
                result["registration"] = register_manifest(connection, Path(result["manifest_path"]))
        finally:
            connection.close()
    print(json.dumps({"results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

