#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = ("SPY", "EFA", "IEF", "TLT", "GLD", "DBC", "UUP", "BIL")
ENDPOINT = "https://api.twelvedata.com/time_series"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_payload(symbol: str, payload: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if payload.get("status") == "error" or "values" not in payload:
        message = payload.get("message") or payload.get("code") or "missing values"
        raise ValueError(f"Twelve Data response error for {symbol}: {message}")
    meta = payload.get("meta", {})
    if meta.get("symbol") and meta["symbol"] != symbol:
        raise ValueError(f"symbol mismatch: requested {symbol}, received {meta['symbol']}")
    rows = []
    seen = set()
    for value in payload["values"]:
        day = value["datetime"][:10]
        numeric = float(value["close"])
        if day in seen:
            raise ValueError(f"duplicate adjusted close: {day}:{symbol}")
        if not math.isfinite(numeric) or numeric <= 0:
            raise ValueError(f"invalid adjusted close: {day}:{symbol}")
        seen.add(day)
        rows.append(
            {
                "date": day,
                "symbol": symbol,
                "adjusted_close": format(numeric, ".12g"),
                "currency": meta.get("currency", "USD"),
                "exchange_timezone": meta.get("exchange_timezone", "America/New_York"),
                "source": "TWELVE_DATA_TIME_SERIES_ADJUST_ALL",
            }
        )
    rows.sort(key=lambda row: row["date"])
    return rows, meta


def _fetch(symbol: str, api_key: str, start: str, end: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    public_params = {
        "symbol": symbol,
        "interval": "1day",
        "start_date": start,
        "end_date": end,
        "outputsize": 5000,
        "order": "ASC",
        "timezone": "America/New_York",
        "adjust": "all",
        "format": "JSON",
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode({**public_params, 'apikey': api_key})}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "fx-research-agent/1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.load(response)
    rows, meta = normalize_payload(symbol, payload)
    return rows, {"endpoint": ENDPOINT, "parameters": public_params, "meta": meta}


def extract(
    output: Path,
    summary_path: Path,
    *,
    api_key: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    provenance = {}
    for index, symbol in enumerate(SYMBOLS):
        symbol_rows, details = _fetch(symbol, api_key, start, end)
        rows.extend(symbol_rows)
        provenance[symbol] = details
        if index + 1 < len(SYMBOLS):
            time.sleep(0.25)
    rows.sort(key=lambda row: (row["date"], row["symbol"]))
    if not rows:
        raise ValueError("Twelve Data extraction returned no rows")
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    dates = {symbol: {row["date"] for row in rows if row["symbol"] == symbol} for symbol in SYMBOLS}
    common = set.intersection(*dates.values())
    summary = {
        "schema": "CROSS_ASSET_ADJUSTED_PRICE_EXTRACTION_V2",
        "source": "TWELVE_DATA_TIME_SERIES",
        "source_role": "INDEPENDENT_CROSS_SOURCE_AND_FORWARD_COLLECTION",
        "adjustment": "ALL_SPLITS_AND_DIVIDENDS",
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
        "api_key_persisted": False,
        "promotion_eligible": False,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract independent adjusted ETF histories from Twelve Data")
    parser.add_argument("--output", type=Path, default=ROOT / "data/external/cross_asset/twelve_data_adjusted_daily.csv.gz")
    parser.add_argument("--summary", type=Path, default=ROOT / "data/external/cross_asset/twelve_data_adjusted_daily.summary.json")
    parser.add_argument("--start", default="2006-01-01")
    parser.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    args = parser.parse_args()
    _load_env(ROOT / ".env")
    api_key = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    if not api_key:
        parser.error("TWELVE_DATA_API_KEY is required in the environment or local .env")
    print(json.dumps(extract(args.output, args.summary, api_key=api_key, start=args.start, end=args.end), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
