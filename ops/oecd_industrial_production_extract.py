#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import urllib.request
from pathlib import Path


AREA_BY_CURRENCY = {"EUR": "EA20", "GBP": "GBR", "JPY": "JPN", "CAD": "CAN", "SEK": "SWE", "NOK": "NOR"}
SOURCE_URL = "https://sdmx.oecd.org/public/rest/v1/data/OECD.SDD.STES,DSD_STES@DF_INDSERV,4.3/.M.PRVM.IX.BTE.Y._Z._Z.N?startPeriod=1990-01"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download() -> bytes:
    request = urllib.request.Request(SOURCE_URL, headers={"Accept": "text/csv", "User-Agent": "fx-research-agent/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def normalize(blob: bytes, output: Path, summary_path: Path) -> dict:
    currency_by_area = {area: currency for currency, area in AREA_BY_CURRENCY.items()}
    rows = []
    seen = set()
    for source in csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))):
        currency = currency_by_area.get(source["REF_AREA"])
        if currency is None:
            continue
        if (source["FREQ"], source["MEASURE"], source["UNIT_MEASURE"], source["ACTIVITY"], source["ADJUSTMENT"]) != ("M", "PRVM", "IX", "BTE", "Y"):
            raise ValueError("OECD industrial-production response contains an unexpected series")
        if source["OBS_STATUS"] not in {"A", "P", "E"}:
            continue
        key = (currency, source["TIME_PERIOD"])
        if key in seen:
            raise ValueError(f"duplicate OECD industrial-production month: {currency}:{source['TIME_PERIOD']}")
        seen.add(key)
        value = float(source["OBS_VALUE"])
        if value <= 0:
            raise ValueError(f"non-positive industrial-production index: {currency}:{source['TIME_PERIOD']}")
        rows.append({"month": source["TIME_PERIOD"], "currency": currency, "area": source["REF_AREA"], "industrial_production_index": format(value, ".12g"), "status": source["OBS_STATUS"], "base_period": source.get("BASE_PER", ""), "source": "OECD_DF_INDSERV_PRVM_IX_BTE_Y"})
    counts = {currency: sum(row["currency"] == currency for row in rows) for currency in AREA_BY_CURRENCY}
    if any(count == 0 for count in counts.values()):
        raise ValueError(f"missing required OECD industrial-production series: {counts}")
    rows.sort(key=lambda row: (row["month"], row["currency"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    months = {currency: {row["month"] for row in rows if row["currency"] == currency} for currency in AREA_BY_CURRENCY}
    common = set.intersection(*months.values())
    summary = {"schema": "FX_OECD_G10_INDUSTRIAL_PRODUCTION_EXTRACTION_V1", "source_url": SOURCE_URL, "source_sha256": sha256_bytes(blob), "output": str(output), "output_sha256": sha256(output), "row_count": len(rows), "observation_count_by_currency": counts, "common_month_count": len(common), "common_window_start": min(common) if common else None, "common_window_end": max(common) if common else None, "information_lag_months": 2, "vintage_policy": "CURRENT_OFFICIAL_VINTAGE"}
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and normalize locked OECD G10-subset industrial production")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(normalize(download(), args.output, args.summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
