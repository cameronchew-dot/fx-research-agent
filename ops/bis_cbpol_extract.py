#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import zipfile
from pathlib import Path


AREA_BY_CURRENCY = {"EUR": "XM", "GBP": "GB", "JPY": "JP", "CHF": "CH", "CAD": "CA", "AUD": "AU", "NZD": "NZ", "SEK": "SE", "NOK": "NO", "USD": "US"}


def code(value: str) -> str:
    return value.split(":", 1)[0].strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(archive: Path, output: Path, summary_path: Path) -> dict:
    currency_by_area = {area: currency for currency, area in AREA_BY_CURRENCY.items()}
    rows = []
    seen = set()
    counts = {currency: 0 for currency in AREA_BY_CURRENCY}
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("BIS policy-rate archive must contain exactly one CSV")
        with bundle.open(members[0]) as binary:
            reader = csv.DictReader((line.decode("utf-8-sig") for line in binary))
            for source in reader:
                if code(source["FREQ:Frequency"]) != "M":
                    continue
                area = code(source["REF_AREA:Reference area"])
                currency = currency_by_area.get(area)
                if currency is None:
                    continue
                period = source["TIME_PERIOD:Time period or range"]
                key = (currency, period)
                if key in seen:
                    raise ValueError(f"duplicate BIS policy-rate month: {currency}:{period}")
                seen.add(key)
                rate = float(source["OBS_VALUE:Observation Value"])
                rows.append({"month": period, "currency": currency, "reference_area": area, "policy_rate_percent": format(rate, ".12g"), "frequency": "MONTHLY", "collection": "END_OF_PERIOD", "source": "BIS_WS_CBPOL_1_0", "status": code(source.get("OBS_STATUS:Observation Status", ""))})
                counts[currency] += 1
    rows.sort(key=lambda row: (row["month"], row["currency"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    by_currency = {currency: {row["month"] for row in rows if row["currency"] == currency} for currency in AREA_BY_CURRENCY}
    common = set.intersection(*by_currency.values())
    summary = {"schema": "FX_BIS_G10_POLICY_RATE_EXTRACTION_V1", "source_url": "https://data.bis.org/static/bulk/WS_CBPOL_csv_flat.zip", "source_sha256": sha256(archive), "output": str(output), "output_sha256": sha256(output), "row_count": len(rows), "month_count_by_currency": counts, "common_month_count": len(common), "common_window_start": min(common) if common else None, "common_window_end": max(common) if common else None}
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract locked G10 monthly central-bank policy rates from BIS WS_CBPOL")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.archive, args.output, args.summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
