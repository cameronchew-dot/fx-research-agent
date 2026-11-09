#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.cross_asset_delayed_trend import (  # noqa: E402
    FORWARD_START_DATE,
    append_forward_ledger,
    evaluate_delayed,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate locked delayed cross-asset trend V2")
    parser.add_argument("--prices", type=Path, default=ROOT / "data/external/cross_asset/twelve_data_adjusted_daily.csv.gz")
    parser.add_argument("--v1-result", type=Path, default=ROOT / "data/results/cross_asset_etf_trend_primary.json")
    parser.add_argument("--cost-bps", type=float, choices=(10.0, 25.0), default=10.0)
    parser.add_argument("--forward-start", default=FORWARD_START_DATE)
    parser.add_argument("--output", type=Path, default=ROOT / "data/results/cross_asset_etf_delayed_trend_v2.json")
    parser.add_argument("--ledger", type=Path, default=ROOT / "data/derived/cross_asset_etf_delayed_trend_forward.jsonl")
    args = parser.parse_args()

    result = evaluate_delayed(
        args.prices,
        args.v1_result,
        one_way_cost_bps=args.cost_bps,
        forward_start=args.forward_start,
    )
    result["provenance"] = {
        "campaign_spec": "config/campaigns/cross_asset_etf_delayed_trend_v2.json",
        "prices_sha256": _sha256(args.prices),
        "v1_result_sha256": _sha256(args.v1_result),
    }
    added = append_forward_ledger(
        args.ledger,
        result["forward"]["rows"],
        source_sha256=result["provenance"]["prices_sha256"],
    )
    result["forward"]["ledger"] = {
        "path": str(args.ledger),
        "new_immutable_rows": added,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
