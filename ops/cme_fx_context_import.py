#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fx_research_agent.futures_context import AGGRESSOR_METHODS, SUPPORTED_PRODUCTS, package_csv_export


def main() -> int:
    parser = argparse.ArgumentParser(description="Package a credential-free CME FX CSV export")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--product", choices=sorted(SUPPORTED_PRODUCTS), required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--source-symbol", required=True)
    parser.add_argument("--contract-mode", choices=("SINGLE_CONTRACT", "CONTINUOUS"), required=True)
    parser.add_argument("--roll-method", required=True)
    parser.add_argument("--price-adjustment", required=True)
    parser.add_argument("--aggressor-side-method", choices=sorted(AGGRESSOR_METHODS), default="NONE")
    parser.add_argument("--freshness-status", choices=("FRESH", "STALE"), default="FRESH")
    parser.add_argument("--gap-status", choices=("COMPLETE", "GAPPED"), default="COMPLETE")
    args = parser.parse_args()
    result = package_csv_export(
        args.csv,
        args.output_dir,
        product=args.product,
        provider=args.provider,
        source_symbol=args.source_symbol,
        contract_mode=args.contract_mode,
        roll_method=args.roll_method,
        price_adjustment=args.price_adjustment,
        aggressor_side_method=args.aggressor_side_method,
        freshness_status=args.freshness_status,
        gap_status=args.gap_status,
    )
    print(json.dumps({key: result[key] for key in ("manifest_path", "payload_path")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
