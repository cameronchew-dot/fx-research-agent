#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.cross_asset_short_term_reversal import evaluate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate locked cross-asset short-term reversal campaign")
    parser.add_argument(
        "--campaign",
        type=Path,
        default=ROOT / "config/campaigns/cross_asset_short_term_reversal_v1.json",
    )
    parser.add_argument(
        "--bars",
        type=Path,
        default=ROOT / "data/external/cross_asset/alpaca_cross_asset_sip_1day.csv.gz",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/results/cross_asset_short_term_reversal_v1.json",
    )
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
    result = evaluate(args.bars, campaign)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
