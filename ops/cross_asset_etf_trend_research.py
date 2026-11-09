#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.cross_asset_trend import evaluate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run locked diversified ETF trend diagnostic")
    parser.add_argument("--prices", type=Path, default=ROOT / "data/external/cross_asset/adjusted_daily.csv.gz")
    parser.add_argument("--cost-bps", type=float, choices=(10.0, 25.0), default=10.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.prices, args.cost_bps)
    campaign_path = ROOT / "config/campaigns/cross_asset_etf_trend_v1.json"
    result["provenance"] = {
        "campaign_spec": str(campaign_path.relative_to(ROOT)),
        "campaign_spec_sha256": hashlib.sha256(campaign_path.read_bytes()).hexdigest(),
        "prices_sha256": hashlib.sha256(args.prices.read_bytes()).hexdigest(),
    }
    development = result["partitions"]["development"]
    oos = result["partitions"]["chronological_oos"]
    dated = result["partitions"]["dated_confirmation"]
    controls = result["controls_dated_confirmation"]
    gates = {
        "minimum_development_months": development["month_count"] >= 96,
        "minimum_chronological_oos_months": oos["month_count"] >= 36,
        "minimum_dated_confirmation_months": dated["month_count"] >= 36,
        "oos_average_excess_cash_return_positive": (oos["average_monthly_excess_cash_return"] or 0) > 0,
        "dated_average_excess_cash_return_positive": (dated["average_monthly_excess_cash_return"] or 0) > 0,
        "dated_information_ratio_at_least_point_five": (dated["annualized_information_ratio_over_cash"] or 0) >= 0.5,
        "dated_positive_year_rate_at_least_sixty_percent": (dated["positive_year_rate"] or 0) >= 0.60,
        "dated_drawdown_within_twenty_five_percent": (dated["maximum_log_drawdown"] or -1) >= -0.25,
        "dated_excess_return_beats_opposite_random_and_stale": all(
            result["dated_average_excess_cash_edge"][name] > 0 for name in ("opposite", "random", "stale")
        ),
        "dated_sharpe_beats_buy_hold": result["dated_sharpe_edge"]["buy_hold"] > 0,
        "dated_drawdown_better_than_buy_hold": dated["maximum_log_drawdown"] > controls["buy_hold"]["maximum_log_drawdown"],
    }
    gates["discovery_source_survivor"] = all(gates.values())
    gates["eligible_for_promotion"] = False
    gates["promotion_blocker"] = "INDEPENDENT_ADJUSTED_PRICE_SOURCE_CONFIRMATION_REQUIRED"
    result["review_gate_assessment"] = gates
    if gates["discovery_source_survivor"]:
        result["interpretation"] = "DISCOVERY_SOURCE_SURVIVOR_REQUIRES_INDEPENDENT_CROSS_SOURCE_CONFIRMATION"
        result["promotion_blockers"] = ["INDEPENDENT_ADJUSTED_PRICE_SOURCE_CONFIRMATION_REQUIRED"]
    else:
        result["interpretation"] = "REJECTED_AS_SPECIFIED_CONTROL_NOT_DEFEATED"
        result["promotion_blockers"] = [
            "LOCKED_REVIEW_GATE_FAILED",
            "INDEPENDENT_ADJUSTED_PRICE_SOURCE_CONFIRMATION_REQUIRED",
        ]
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
