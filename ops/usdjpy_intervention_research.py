#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fx_research_agent.usdjpy_intervention import evaluate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run locked retrospective USD/JPY intervention episode audit")
    parser.add_argument("--spot", type=Path, default=ROOT / "data/external/bis/usdjpy_daily_average.csv.gz")
    parser.add_argument("--events", type=Path, default=ROOT / "data/external/mof/usdjpy_interventions.csv.gz")
    parser.add_argument("--cost-bps", type=float, choices=(5.0, 10.0), default=5.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.spot, args.events, args.cost_bps)
    campaign_path = ROOT / "config/campaigns/usdjpy_mof_intervention_episode_v1.json"
    result["provenance"] = {"campaign_spec": str(campaign_path.relative_to(ROOT)), "campaign_spec_sha256": hashlib.sha256(campaign_path.read_bytes()).hexdigest(), "spot_sha256": hashlib.sha256(args.spot.read_bytes()).hexdigest(), "events_sha256": hashlib.sha256(args.events.read_bytes()).hexdigest()}
    development, oos, dated = (result["partitions"][name] for name in ("development", "chronological_oos", "dated_confirmation"))
    edges = [value for value in result["dated_control_edge"].values() if value is not None]
    gates = {"minimum_development_episodes": development["episode_count"] >= 30, "minimum_chronological_oos_episodes": oos["episode_count"] >= 10, "minimum_dated_confirmation_episodes": dated["episode_count"] >= 10, "minimum_dated_control_episodes_each": all(summary["episode_count"] >= 10 for summary in result["controls_dated_confirmation"].values()), "oos_average_policy_aligned_net_return_positive": oos["average_net_policy_aligned_return"] is not None and oos["average_net_policy_aligned_return"] > 0, "dated_average_policy_aligned_net_return_positive": dated["average_net_policy_aligned_return"] is not None and dated["average_net_policy_aligned_return"] > 0, "dated_all_available_control_edges_positive": len(edges) == 3 and all(value > 0 for value in edges)}
    gates["eligible_only_for_observable_proxy_design"] = all(gates.values())
    gates["direct_strategy_or_lifecycle_eligibility"] = False
    result["review_gate_assessment"] = gates
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
