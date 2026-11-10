#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.alpaca_intraday import extract_spy_minute_bars  # noqa: E402


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export historical SPY SIP minute bars from Alpaca")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "external" / "cross_asset" / "alpaca_spy_sip_1min.csv.gz",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "data" / "external" / "cross_asset" / "alpaca_spy_sip_1min.summary.json",
    )
    parser.add_argument("--start", default="2016-01-01T00:00:00Z")
    parser.add_argument("--end", default="2026-11-07T00:00:00Z")
    args = parser.parse_args()
    _load_env(ROOT / ".env")
    key_id = os.environ.get("ALPACA_DATA_API_KEY_ID", "").strip()
    secret = os.environ.get("ALPACA_DATA_API_SECRET_KEY", "").strip()
    if not key_id or not secret:
        parser.error("ALPACA_DATA_API_KEY_ID and ALPACA_DATA_API_SECRET_KEY are required")
    result = extract_spy_minute_bars(
        args.output,
        args.summary,
        api_key_id=key_id,
        api_secret_key=secret,
        start=args.start,
        end=args.end,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
