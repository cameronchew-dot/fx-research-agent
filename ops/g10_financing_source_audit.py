#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.financing_sources import audit_paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Campaign 4 financing-source readiness")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "config" / "g10_financing_source_catalog.json",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "config" / "g10_literature_panel_contract.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_paths(args.catalog, args.contract)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["campaign_4_data_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
