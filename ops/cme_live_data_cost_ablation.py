#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.cme_cost_ablation import write_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the locked historical CME live-data cost diagnostic")
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "config/cme_live_data_cost_ablation_v1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/results/cme_live_data_cost_ablation_v1.json",
    )
    args = parser.parse_args()
    report = write_report(root=ROOT, contract_path=args.contract, output_path=args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
