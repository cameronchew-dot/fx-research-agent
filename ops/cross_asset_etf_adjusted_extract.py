#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SYMBOLS = ("SPY", "EFA", "IEF", "TLT", "GLD", "DBC", "UUP", "BIL")
SOURCE_TEMPLATE = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch(symbol: str, period1: int, period2: int) -> tuple[list[dict], dict]:
    params = urllib.parse.urlencode(
        {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "div,splits",
        }
    )
    url = f"{SOURCE_TEMPLATE.format(symbol=symbol)}?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("chart", {}).get("error"):
        raise ValueError(f"provider error for {symbol}: {payload['chart']['error']}")
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    if len(timestamps) != len(adjusted):
        raise ValueError(f"timestamp/value length mismatch for {symbol}")
    rows = []
    for timestamp, value in zip(timestamps, adjusted):
        if value is None:
            continue
        numeric = float(value)
        if not math.isfinite(numeric) or numeric <= 0:
            raise ValueError(f"invalid adjusted close for {symbol}:{timestamp}")
        rows.append(
            {
                "date": datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat(),
                "symbol": symbol,
                "adjusted_close": format(numeric, ".12g"),
                "currency": result.get("meta", {}).get("currency", "USD"),
                "exchange_timezone": result.get("meta", {}).get("exchangeTimezoneName", "America/New_York"),
                "source": "YAHOO_CHART_ADJUSTED_CLOSE",
            }
        )
    return rows, {"url": url, "meta": result.get("meta", {}), "event_types": sorted(result.get("events", {}))}


def extract(output: Path, summary_path: Path, *, start: str = "1990-01-01", end: str | None = None) -> dict:
    period1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    end_value = end or datetime.now(timezone.utc).date().isoformat()
    period2 = int(datetime.fromisoformat(end_value).replace(tzinfo=timezone.utc).timestamp()) + 86400
    rows = []
    provenance = {}
    for index, symbol in enumerate(SYMBOLS):
        symbol_rows, symbol_provenance = _fetch(symbol, period1, period2)
        rows.extend(symbol_rows)
        provenance[symbol] = symbol_provenance
        if index + 1 < len(SYMBOLS):
            time.sleep(0.5)
    rows.sort(key=lambda row: (row["date"], row["symbol"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    dates = {symbol: {row["date"] for row in rows if row["symbol"] == symbol} for symbol in SYMBOLS}
    common = set.intersection(*dates.values())
    summary = {
        "schema": "CROSS_ASSET_ADJUSTED_PRICE_EXTRACTION_V1",
        "source": "YAHOO_CHART_API",
        "source_role": "DISCOVERY_ONLY_REQUIRES_INDEPENDENT_CONFIRMATION",
        "symbols": list(SYMBOLS),
        "row_count": len(rows),
        "row_count_by_symbol": {symbol: len(values) for symbol, values in dates.items()},
        "common_day_count": len(common),
        "common_window_start": min(common) if common else None,
        "common_window_end": max(common) if common else None,
        "output": str(output),
        "output_sha256": _sha256(output),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provenance": provenance,
        "promotion_eligible": False,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract adjusted ETF histories for cross-asset research")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--start", default="1990-01-01")
    parser.add_argument("--end")
    args = parser.parse_args()
    print(json.dumps(extract(args.output, args.summary, start=args.start, end=args.end), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
