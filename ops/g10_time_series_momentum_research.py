#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.g10_time_series_momentum import evaluate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run locked G10 daily time-series momentum spot diagnostic")
    parser.add_argument("--spot", type=Path, default=ROOT / "data/external/bis/g10_daily_spot.csv.gz")
    parser.add_argument("--cost-bps", type=float, choices=(5.0, 10.0), default=5.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.spot, args.cost_bps)
    campaign_path = ROOT / "config/campaigns/g10_daily_time_series_momentum_spot_diagnostic_v1.json"
    result["provenance"] = {
        "campaign_spec": str(campaign_path.relative_to(ROOT)),
        "campaign_spec_sha256": hashlib.sha256(campaign_path.read_bytes()).hexdigest(),
        "spot_sha256": hashlib.sha256(args.spot.read_bytes()).hexdigest(),
    }
    development = result["partitions"]["development"]
    oos = result["partitions"]["chronological_oos"]
    dated = result["partitions"]["dated_confirmation"]
    gates = {
        "minimum_development_weeks": development["week_count"] >= 500,
        "minimum_chronological_oos_weeks": oos["week_count"] >= 150,
        "minimum_dated_confirmation_weeks": dated["week_count"] >= 150,
        "oos_average_net_spot_return_positive": (oos["average_weekly_net_return"] or 0) > 0,
        "dated_confirmation_average_net_spot_return_positive": (dated["average_weekly_net_return"] or 0) > 0,
        "dated_confirmation_sharpe_at_least_point_five": (dated["annualized_sharpe_zero_rate"] or 0) >= 0.5,
        "dated_confirmation_positive_year_rate_at_least_sixty_percent": (dated["positive_year_rate"] or 0) >= 0.60,
        "dated_confirmation_drawdown_within_twenty_percent": (dated["maximum_log_drawdown"] or -1) >= -0.20,
        "dated_confirmation_all_control_edges_positive": all(value > 0 for value in result["dated_control_edge"].values()),
    }
    gates["spot_diagnostic_survivor"] = all(gates.values())
    gates["eligible_for_promotion"] = False
    gates["promotion_blocker"] = "HISTORICAL_FINANCING_OR_FORWARD_POINTS_UNAVAILABLE"
    result["review_gate_assessment"] = gates
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
