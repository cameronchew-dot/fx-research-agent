#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.alpaca_intraday import extract_symbol_minute_bars  # noqa: E402


DEFAULT_SYMBOLS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "SPY")


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
    parser = argparse.ArgumentParser(description="Export the locked Alpaca sector ETF panel")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--start", default="2016-01-01T00:00:00Z")
    parser.add_argument("--end", default="2026-11-07T00:00:00Z")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    symbols = tuple(symbol.strip().upper() for symbol in args.symbols)
    if len(set(symbols)) != len(symbols):
        parser.error("symbols must be unique")
    if args.workers < 1 or args.workers > 3:
        parser.error("workers must be between 1 and 3")

    _load_env(ROOT / ".env")
    key_id = os.environ.get("ALPACA_DATA_API_KEY_ID", "").strip()
    secret = os.environ.get("ALPACA_DATA_API_SECRET_KEY", "").strip()
    if not key_id or not secret:
        parser.error("ALPACA_DATA_API_KEY_ID and ALPACA_DATA_API_SECRET_KEY are required")

    def collect(symbol: str) -> dict[str, object]:
        stem = symbol.lower()
        return extract_symbol_minute_bars(
            ROOT / "data" / "external" / "cross_asset" / f"alpaca_{stem}_sip_15min.csv.gz",
            ROOT / "data" / "external" / "cross_asset" / f"alpaca_{stem}_sip_15min.summary.json",
            api_key_id=key_id,
            api_secret_key=secret,
            start=args.start,
            end=args.end,
            symbol=symbol,
            timeframe="15Min",
        )

    results: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(collect, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            results[symbol] = future.result()
    print(json.dumps({symbol: results[symbol] for symbol in sorted(results)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
