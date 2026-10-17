#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import zipfile
from pathlib import Path


def code(value: str) -> str:
    return value.split(":", 1)[0].strip()


def extract(archive: Path, output: Path, summary_path: Path) -> dict:
    rows, seen = [], set()
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("BIS archive must contain exactly one CSV")
        with bundle.open(members[0]) as binary:
            for source in csv.DictReader((line.decode("utf-8-sig") for line in binary)):
                if code(source["FREQ:Frequency"]) != "D" or code(source["COLLECTION:Collection"]) != "A":
                    continue
                if (code(source["REF_AREA:Reference area"]), code(source["CURRENCY:Currency"])) != ("JP", "JPY"):
                    continue
                date = source["TIME_PERIOD:Time period or range"]
                if date in seen:
                    raise ValueError(f"duplicate BIS USD/JPY day: {date}")
                seen.add(date)
                value = float(source["OBS_VALUE:Observation Value"])
                if value <= 0:
                    raise ValueError(f"non-positive BIS USD/JPY observation: {date}")
                rows.append({"date": date, "usd_jpy": format(value, ".12g"), "collection": "DAILY_AVERAGE", "source": "BIS_WS_XRU_1_0"})
    rows.sort(key=lambda row: row["date"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"schema": "FX_BIS_USDJPY_DAILY_EXTRACTION_V1", "source_archive": str(archive), "source_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "output": str(output), "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "row_count": len(rows), "window_start": rows[0]["date"], "window_end": rows[-1]["date"], "frequency": "DAILY", "collection": "AVERAGE"}
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract official BIS daily-average USD/JPY spot")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.archive, args.output, args.summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
