#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import urllib.parse
import urllib.request
from pathlib import Path


SOURCE_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
FIELDS = (
    "id,market_and_exchange_names,report_date_as_yyyy_mm_dd,contract_market_name,"
    "cftc_contract_market_code,open_interest_all,lev_money_positions_long,"
    "lev_money_positions_short,futonly_or_combined"
)


def download(contract: dict) -> bytes:
    codes = sorted(value["cftc_contract_market_code"] for value in contract["instruments"].values())
    quoted = ",".join(f"'{value}'" for value in codes)
    query = urllib.parse.urlencode(
        {
            "$select": FIELDS,
            "$where": f"cftc_contract_market_code in ({quoted})",
            "$order": "report_date_as_yyyy_mm_dd,cftc_contract_market_code",
            "$limit": "50000",
        }
    )
    request = urllib.request.Request(
        f"{SOURCE_URL}?{query}", headers={"User-Agent": "fx-research-agent/1.0"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def normalize(blob: bytes, contract: dict, output: Path, summary_path: Path) -> dict:
    source_rows = json.loads(blob)
    if not isinstance(source_rows, list):
        raise ValueError("CFTC response must be a JSON row list")
    code_to_instrument = {
        value["cftc_contract_market_code"]: (instrument, value["contract_market_name"])
        for instrument, value in contract["instruments"].items()
    }
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in source_rows:
        code = str(source.get("cftc_contract_market_code", ""))
        if code not in code_to_instrument:
            continue
        instrument, expected_name = code_to_instrument[code]
        if str(source.get("contract_market_name", "")).strip() != expected_name:
            raise ValueError(f"unexpected CFTC contract identity for {code}")
        if source.get("futonly_or_combined") != "FutOnly":
            raise ValueError(f"non-futures-only CFTC row for {code}")
        report_date = str(source["report_date_as_yyyy_mm_dd"])[:10]
        key = (instrument, report_date)
        if key in seen:
            raise ValueError(f"duplicate CFTC report: {key}")
        seen.add(key)
        open_interest = float(source["open_interest_all"])
        long_positions = float(source["lev_money_positions_long"])
        short_positions = float(source["lev_money_positions_short"])
        if open_interest <= 0:
            raise ValueError(f"non-positive CFTC open interest: {key}")
        rows.append(
            {
                "report_id": str(source["id"]),
                "report_date": report_date,
                "instrument": instrument,
                "contract_market_name": expected_name,
                "cftc_contract_market_code": code,
                "open_interest": format(open_interest, ".12g"),
                "leveraged_money_long": format(long_positions, ".12g"),
                "leveraged_money_short": format(short_positions, ".12g"),
                "leveraged_money_net_share": format(
                    (long_positions - short_positions) / open_interest, ".12g"
                ),
                "source": "CFTC_TFF_FUTURES_ONLY",
            }
        )
    rows.sort(key=lambda row: (row["report_date"], row["instrument"]))
    expected = set(contract["instruments"])
    observed = {row["instrument"] for row in rows}
    if observed != expected:
        raise ValueError(f"incomplete CFTC instrument coverage: {sorted(expected - observed)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = {
        instrument: sum(row["instrument"] == instrument for row in rows)
        for instrument in sorted(expected)
    }
    dates = [row["report_date"] for row in rows]
    summary = {
        "schema": "FX_CFTC_TFF_POSITIONING_EXTRACTION_V1",
        "source_url": SOURCE_URL,
        "source_sha256": hashlib.sha256(blob).hexdigest(),
        "output": str(output),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "row_count": len(rows),
        "report_count_by_instrument": counts,
        "window_start": min(dates),
        "window_end": max(dates),
        "point_in_time_policy": contract["availability_policy"],
        "research_only": True,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Download official CFTC TFF FX positioning")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    print(json.dumps(normalize(download(contract), contract, args.output, args.summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
