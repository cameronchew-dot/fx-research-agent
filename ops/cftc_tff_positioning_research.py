#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.cftc_tff_positioning import evaluate_development  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run locked development-only CFTC TFF crowding research")
    parser.add_argument("--campaign", type=Path, default=ROOT / "config/campaigns/cftc_tff_fx_crowding_reversal_v1.json")
    parser.add_argument("--reports", type=Path, default=ROOT / "data/external/cftc/tff_fx_positioning.csv.gz")
    parser.add_argument("--inbox", type=Path, default=ROOT / "data/inbox")
    parser.add_argument("--output", type=Path, default=ROOT / "data/results/cftc_tff_fx_crowding_reversal_development.json")
    parser.add_argument("--events", type=Path, default=ROOT / "data/results/cftc_tff_fx_crowding_reversal_development.events.json.gz")
    args = parser.parse_args()
    campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
    result = evaluate_development(args.reports, args.inbox, campaign)
    events = result.pop("events")
    args.events.parent.mkdir(parents=True, exist_ok=True)
    with args.events.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as handle:
            handle.write((json.dumps(events, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    result["provenance"] = {
        "campaign_sha256": hashlib.sha256(args.campaign.read_bytes()).hexdigest(),
        "reports_sha256": hashlib.sha256(args.reports.read_bytes()).hexdigest(),
        "event_ledger": str(args.events.relative_to(ROOT)) if args.events.is_relative_to(ROOT) else str(args.events),
        "event_ledger_sha256": hashlib.sha256(args.events.read_bytes()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
