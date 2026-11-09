#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.cme_agent_context_diagnostic import evaluate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate locked causal 6E context against EUR/USD agent episodes")
    parser.add_argument(
        "--campaign",
        type=Path,
        default=ROOT / "config" / "campaigns" / "eur_cme_bar_context_diagnostic_v1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "results" / "eur_cme_bar_context_diagnostic_v1.json",
    )
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
    result = evaluate(ROOT, campaign)
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
