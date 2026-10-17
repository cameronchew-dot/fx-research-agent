from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any

from .storage import canonical_json


PANEL_SCHEMA = "FX_G10_MONTHLY_EXCESS_RETURN_PANEL_V1"
PANEL_DATA_CLASSES = {
    "COMPLETED_DAILY_BID_ASK_CANDLES",
    "MONTHLY_FINANCING_OR_FORWARD_POINTS",
    "CURRENCY_EXCESS_RETURNS",
}
ALLOWED_FINANCING_SOURCES = {
    "OBSERVED_ONE_MONTH_FORWARD_POINTS",
    "OBSERVED_HISTORICAL_FINANCING_RETURN",
}
EXPECTED_CURRENCY_BY_INSTRUMENT = {
    "EUR_USD": "EUR",
    "GBP_USD": "GBP",
    "USD_JPY": "JPY",
    "USD_CHF": "CHF",
    "USD_CAD": "CAD",
    "AUD_USD": "AUD",
    "NZD_USD": "NZD",
    "USD_SEK": "SEK",
    "USD_NOK": "NOK",
}


def _read_payload(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"literature panel {field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"literature panel {field} must be finite")
    return parsed


def validate_panel_payload(manifest: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    instrument = str(manifest.get("instrument") or "")
    expected_currency = EXPECTED_CURRENCY_BY_INSTRUMENT.get(instrument)
    if expected_currency is None:
        raise ValueError(f"unsupported G10 literature-panel instrument: {instrument}")
    if set(str(value) for value in manifest.get("data_classes", [])) != PANEL_DATA_CLASSES:
        raise ValueError("literature panel must declare all three locked panel data classes")
    if payload.get("schema") != PANEL_SCHEMA:
        raise ValueError("unsupported literature panel payload schema")
    if payload.get("instrument") != instrument:
        raise ValueError("literature panel payload instrument differs from manifest")
    if payload.get("normalized_currency") != expected_currency:
        raise ValueError("literature panel normalized currency does not match instrument")
    if payload.get("quote_normalization") != "USD_VALUE_OF_ONE_UNIT_FOREIGN_CURRENCY":
        raise ValueError("literature panel quote normalization is not the locked convention")

    rows = payload.get("monthly_rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("literature panel requires monthly rows")
    seen: dict[str, dict[str, Any]] = {}
    previous_month = ""
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("literature panel row must be an object")
        month = str(row.get("month_end_utc") or "")
        if not month.endswith("Z") or len(month) < 20:
            raise ValueError("literature panel month_end_utc must be an ISO UTC timestamp")
        if previous_month and month <= previous_month:
            raise ValueError("literature panel months must be unique and strictly increasing")
        previous_month = month
        if row.get("instrument") != instrument or row.get("normalized_currency") != expected_currency:
            raise ValueError("literature panel row identity differs from payload")
        financing_source = str(row.get("financing_source_type") or "")
        if financing_source not in ALLOWED_FINANCING_SOURCES:
            raise ValueError("literature panel financing must be observed, not inferred or zero-filled")
        if row.get("transaction_cost_source") != "HISTORICAL_BID_ASK":
            raise ValueError("literature panel transaction cost must come from historical bid/ask")

        spot = _finite_number(row.get("normalized_spot_return"), "normalized_spot_return")
        financing = _finite_number(row.get("financing_return"), "financing_return")
        excess = _finite_number(row.get("gross_excess_return"), "gross_excess_return")
        cost = _finite_number(row.get("round_trip_cost_return"), "round_trip_cost_return")
        net = _finite_number(row.get("net_excess_return"), "net_excess_return")
        if cost < 0:
            raise ValueError("literature panel round-trip cost cannot be negative")
        if not math.isclose(excess, spot + financing, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError("literature panel gross excess return arithmetic mismatch")
        if not math.isclose(net, excess - cost, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError("literature panel net excess return arithmetic mismatch")
        if month in seen and canonical_json(seen[month]) != canonical_json(row):
            raise ValueError(f"conflicting immutable literature month: {instrument}:{month}")
        seen[month] = row
    return payload


def load_validated_panel(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    payload_path = Path(manifest["payload_path"])
    if not payload_path.is_absolute():
        payload_path = manifest_path.parent / payload_path
    return validate_panel_payload(manifest, _read_payload(payload_path))


def panel_status(connection, inbox_dir: Path) -> dict[str, Any]:
    months_by_instrument: dict[str, set[str]] = {
        instrument: set() for instrument in EXPECTED_CURRENCY_BY_INSTRUMENT
    }
    manifest_ids: list[str] = []
    errors: list[dict[str, str]] = []
    for row in connection.execute(
        "SELECT payload_json FROM market_data_manifests WHERE usable_for_testing=1 ORDER BY manifest_id"
    ).fetchall():
        manifest = json.loads(row["payload_json"])
        instrument = str(manifest.get("instrument") or "")
        if instrument not in months_by_instrument:
            continue
        if not PANEL_DATA_CLASSES.issubset(set(manifest.get("data_classes", []))):
            continue
        manifest_path = inbox_dir / f"{manifest['manifest_id']}.manifest.json"
        if not manifest_path.is_file():
            matches = list(inbox_dir.glob(f"*{manifest['manifest_id']}*.manifest.json"))
            if len(matches) != 1:
                errors.append({"manifest_id": str(manifest["manifest_id"]), "error": "manifest_copy_unavailable"})
                continue
            manifest_path = matches[0]
        try:
            from .market_data import validate_manifest

            disk_manifest = validate_manifest(manifest_path)
            if disk_manifest != manifest:
                raise ValueError("registered literature manifest differs from inbox copy")
            payload = load_validated_panel(manifest_path, manifest)
            manifest_ids.append(str(manifest["manifest_id"]))
            months_by_instrument[instrument].update(
                str(item["month_end_utc"]) for item in payload["monthly_rows"]
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"manifest_id": str(manifest["manifest_id"]), "error": str(exc)})

    common_months = set.intersection(*months_by_instrument.values()) if months_by_instrument else set()
    minimum_required = 192
    missing_instruments = sorted(
        instrument for instrument, months in months_by_instrument.items() if not months
    )
    return {
        "schema": "FX_G10_LITERATURE_PANEL_STATUS_V1",
        "panel_status": (
            "READY"
            if len(common_months) >= minimum_required and not missing_instruments and not errors
            else "BLOCKED"
        ),
        "manifest_ids": sorted(manifest_ids),
        "month_count_by_instrument": {
            instrument: len(months) for instrument, months in sorted(months_by_instrument.items())
        },
        "common_month_count": len(common_months),
        "common_window_start_utc": min(common_months) if common_months else None,
        "common_window_end_utc": max(common_months) if common_months else None,
        "minimum_required_common_months": minimum_required,
        "missing_instruments": missing_instruments,
        "errors": errors,
        "spot_only_allowed": False,
        "zero_financing_fill_allowed": False,
        "order_authority": False,
    }
