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


AREA_BY_CURRENCY = {"EUR": "EA20", "GBP": "GBR", "JPY": "JPN", "CHF": "CHE", "CAD": "CAN", "AUD": "AUS", "NZD": "NZL", "SEK": "SWE", "NOK": "NOR", "USD": "USA"}
BASE = "https://sdmx.oecd.org/public/rest/v1/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0"


def series_url(area: str) -> str:
    frequency = "Q" if area in {"AUS", "NZL"} else "M"
    return f"{BASE}/{area}.{frequency}.N.CPI.IX._T.N._Z?startPeriod=1970-01"


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "text/csv", "User-Agent": "fx-research-agent/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def normalize(blobs: dict[str, bytes], output: Path, summary_path: Path) -> dict:
    rows = []
    counts = {}
    hashes = {}
    for currency, area in AREA_BY_CURRENCY.items():
        blob = blobs[area]
        hashes[area] = hashlib.sha256(blob).hexdigest()
        selected = []
        for row in csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))):
            if row["REF_AREA"] != area or row["OBS_STATUS"] not in {"A", "P", "E"}:
                continue
            value = float(row["OBS_VALUE"])
            if value <= 0:
                raise ValueError(f"non-positive CPI: {area}:{row['TIME_PERIOD']}")
            selected.append({"period": row["TIME_PERIOD"], "currency": currency, "area": area, "frequency": row["FREQ"], "cpi_index": format(value, ".12g"), "status": row["OBS_STATUS"], "base_period": row.get("BASE_PER", ""), "source": "OECD_DF_PRICES_ALL"})
        if not selected:
            raise ValueError(f"no CPI observations for {area}")
        counts[currency] = len(selected)
        rows.extend(selected)
    rows.sort(key=lambda row: (row["period"], row["currency"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"schema": "FX_OECD_G10_CPI_EXTRACTION_V1", "source": "OECD_DF_PRICES_ALL", "series_urls": {area: series_url(area) for area in sorted(set(AREA_BY_CURRENCY.values()))}, "source_sha256_by_area": hashes, "output": str(output), "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "row_count": len(rows), "observation_count_by_currency": counts, "information_lag_months": 2, "quarterly_policy": "AUSTRALIA_AND_NEW_ZEALAND_AS_OF_JOIN_NO_INTERPOLATION"}
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and normalize locked OECD G10 CPI series")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    blobs = {area: download(series_url(area)) for area in sorted(set(AREA_BY_CURRENCY.values()))}
    print(json.dumps(normalize(blobs, args.output, args.summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
