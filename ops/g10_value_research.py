#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fx_research_agent.g10_value import evaluate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the locked G10 real-exchange-rate value replication")
    parser.add_argument("--spot", type=Path, default=ROOT / "data/external/bis/g10_monthly_spot.csv.gz")
    parser.add_argument("--cpi", type=Path, default=ROOT / "data/external/oecd/g10_cpi.csv.gz")
    parser.add_argument("--cost-bps", type=float, choices=(5.0, 10.0), default=5.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.spot, args.cpi, args.cost_bps)
    campaign_path = ROOT / "config/campaigns/g10_real_exchange_rate_value_v1.json"
    result["provenance"] = {
        "campaign_spec": str(campaign_path.relative_to(ROOT)),
        "campaign_spec_sha256": hashlib.sha256(campaign_path.read_bytes()).hexdigest(),
        "spot_sha256": hashlib.sha256(args.spot.read_bytes()).hexdigest(),
        "cpi_sha256": hashlib.sha256(args.cpi.read_bytes()).hexdigest(),
    }
    oos = result["partitions"]["chronological_oos"]
    dated = result["partitions"]["dated_confirmation"]
    result["review_gate_assessment"] = {
        "minimum_development_months": result["partitions"]["development"]["month_count"] >= 120,
        "minimum_chronological_oos_months": oos["month_count"] >= 36,
        "minimum_dated_confirmation_months": dated["month_count"] >= 36,
        "oos_average_net_spot_return_positive": oos["average_monthly_net_return"] > 0,
        "dated_confirmation_average_net_spot_return_positive": dated["average_monthly_net_return"] > 0,
        "dated_confirmation_all_control_edges_positive": all(value > 0 for value in result["dated_control_edge"].values()),
    }
    result["review_gate_assessment"]["eligible_for_human_review"] = all(result["review_gate_assessment"].values())
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
