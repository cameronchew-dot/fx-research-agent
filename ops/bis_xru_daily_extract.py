#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import zipfile
from pathlib import Path

from bis_xru_extract import SERIES, code


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(archive: Path, output: Path, summary_path: Path) -> dict:
    rows: list[dict[str, str]] = []
    excluded_non_finite_observation_count = 0
    by_instrument: dict[str, set[str]] = {instrument: set() for instrument, _ in SERIES.values()}
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("BIS archive must contain exactly one CSV")
        with bundle.open(members[0]) as binary:
            reader = csv.DictReader((line.decode("utf-8-sig") for line in binary))
            for source in reader:
                if code(source["FREQ:Frequency"]) != "D" or code(source["COLLECTION:Collection"]) != "A":
                    continue
                identity = (code(source["REF_AREA:Reference area"]), code(source["CURRENCY:Currency"]))
                selected = SERIES.get(identity)
                if selected is None:
                    continue
                instrument, currency = selected
                period = str(source["TIME_PERIOD:Time period or range"])
                local_per_usd = float(source["OBS_VALUE:Observation Value"])
                if not math.isfinite(local_per_usd):
                    excluded_non_finite_observation_count += 1
                    continue
                if local_per_usd <= 0:
                    raise ValueError(f"non-positive BIS observation: {instrument}:{period}")
                if period in by_instrument[instrument]:
                    raise ValueError(f"duplicate BIS day: {instrument}:{period}")
                by_instrument[instrument].add(period)
                rows.append(
                    {
                        "date": period,
                        "instrument": instrument,
                        "normalized_currency": currency,
                        "bis_currency_units_per_usd": format(local_per_usd, ".12g"),
                        "normalized_usd_per_foreign_currency": format(1.0 / local_per_usd, ".12g"),
                        "reference_area": identity[0],
                        "collection": "DAILY_AVERAGE",
                        "availability": code(source.get("AVAILABILITY:Availability", "")),
                        "source": "BIS_WS_XRU_1_0",
                        "data_scope": "SPOT_ONLY_NOT_EXECUTABLE_BID_ASK_OR_EXCESS_RETURN",
                    }
                )
    if not rows:
        raise ValueError("no matching daily BIS observations")
    rows.sort(key=lambda row: (row["date"], row["instrument"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    common = set.intersection(*by_instrument.values()) if by_instrument else set()
    summary = {
        "schema": "FX_BIS_G10_DAILY_SPOT_EXTRACTION_V1",
        "source_url": "https://data.bis.org/static/bulk/WS_XRU_csv_flat.zip",
        "source_archive": str(archive),
        "source_sha256": sha256(archive),
        "output": str(output),
        "output_sha256": sha256(output),
        "frequency": "DAILY",
        "collection": "AVERAGE_OF_OBSERVATIONS_THROUGH_PERIOD",
        "quote_normalization": "USD_VALUE_OF_ONE_UNIT_FOREIGN_CURRENCY",
        "row_count": len(rows),
        "excluded_non_finite_observation_count": excluded_non_finite_observation_count,
        "day_count_by_instrument": {
            instrument: len(days) for instrument, days in sorted(by_instrument.items())
        },
        "common_day_count": len(common),
        "common_window_start": min(common) if common else None,
        "common_window_end": max(common) if common else None,
        "historical_financing_requirement_satisfied": False,
        "data_scope": "SPOT_ONLY_NOT_EXECUTABLE_BID_ASK_OR_EXCESS_RETURN",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract the G10 daily spot panel from BIS WS_XRU")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.archive, args.output, args.summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
