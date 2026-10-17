#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import urllib.request
from pathlib import Path


SOURCE_URL = "https://www.mof.go.jp/english/policy/international_policy/reference/feio/foreign_exchange_intervention_operations.csv"
MONTHS = {name[:3].lower(): number for number, name in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}


def download() -> bytes:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "fx-research-agent/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def normalize(blob: bytes, output: Path, summary_path: Path) -> dict:
    source_rows = list(csv.reader(io.StringIO(blob.decode("cp932"))))
    year = month = None
    rows = []
    for source in source_rows[15:]:
        if len(source) < 9:
            continue
        if source[3].strip():
            try:
                year = int(source[3])
            except ValueError:
                continue
        if source[4].strip():
            month = MONTHS.get(source[4].strip()[:3].lower())
        try:
            day = int(source[5])
            amount = float(source[6].replace(",", ""))
        except (TypeError, ValueError):
            continue
        pair = source[8].replace("　", " ").strip()
        if year is None or month is None or "US dollar" not in pair or "Japanese yen" not in pair:
            continue
        if "US dollar (bought)" in pair and "Japanese yen (sold)" in pair:
            direction = 1
        elif "US dollar (sold)" in pair and "Japanese yen (bought)" in pair:
            direction = -1
        else:
            continue
        rows.append({"date": dt.date(year, month, day).isoformat(), "policy_direction_usdjpy": direction, "amount_100m_yen": format(amount, ".12g"), "currency_pair": pair, "source": "JAPAN_MOF_DAILY_INTERVENTION"})
    rows.sort(key=lambda row: row["date"])
    if not rows or len({row["date"] for row in rows}) != len(rows):
        raise ValueError("MOF USD/JPY intervention rows are empty or contain duplicate dates")
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = {str(direction): sum(int(row["policy_direction_usdjpy"]) == direction for row in rows) for direction in (-1, 1)}
    summary = {"schema": "FX_MOF_USDJPY_INTERVENTION_EXTRACTION_V1", "source_url": SOURCE_URL, "source_sha256": hashlib.sha256(blob).hexdigest(), "output": str(output), "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "event_count": len(rows), "event_count_by_direction": counts, "window_start": rows[0]["date"], "window_end": rows[-1]["date"], "publication_policy": "RETROSPECTIVE_EVENT_LABELS_NOT_REAL_TIME_SIGNAL"}
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and normalize official MOF USD/JPY intervention dates")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(normalize(download(), args.output, args.summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
