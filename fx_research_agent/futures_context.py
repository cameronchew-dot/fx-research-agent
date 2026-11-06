from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


FUTURES_DATA_CLASSES = {
    "CME_FX_TRADES",
    "CME_FX_AGGRESSOR_IMBALANCE",
    "CME_FX_ORDER_BOOK",
    "CME_FX_OPEN_INTEREST",
    "CME_SPOT_BASIS",
}

SUPPORTED_PRODUCTS = {"6E", "6J", "6A"}
AGGRESSOR_METHODS = {"NONE", "PROVIDER_SUPPLIED", "BID_ASK_CLASSIFIED"}
REQUIRED_BAR_FIELDS = {
    "window_start_utc",
    "window_end_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_count",
}


def _utc(value: Any, field: str) -> str:
    text = str(value or "")
    if not text.endswith("Z"):
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO-8601 timestamp") from exc
    return text


def _finite_nonnegative(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and nonnegative")
    return number


def validate_futures_payload(manifest: dict[str, Any], payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != "CME_FX_CONTEXT_EXPORT_V1":
        raise ValueError("unsupported CME FX context payload schema")
    product = str(payload.get("canonical_product") or "")
    if product not in SUPPORTED_PRODUCTS or str(manifest.get("instrument")) != product:
        raise ValueError("CME FX payload product must match the manifest instrument")
    provider = str(payload.get("source_provider") or "").strip()
    source_symbol = str(payload.get("source_symbol") or "").strip()
    if not provider or not source_symbol:
        raise ValueError("CME FX payload requires source provider and symbol provenance")
    provenance = manifest.get("provider_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("CME FX manifest requires provider provenance")
    if str(provenance.get("provider") or "") != provider or str(provenance.get("source_symbol") or "") != source_symbol:
        raise ValueError("CME FX manifest and payload provider provenance must match")
    metadata = payload.get("contract_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("CME FX payload requires contract metadata")
    if not metadata.get("contract_mode") or not metadata.get("roll_method") or not metadata.get("price_adjustment"):
        raise ValueError("CME FX contract mode, roll method, and price adjustment are required")
    method = str(payload.get("aggressor_side_method") or "NONE")
    if method not in AGGRESSOR_METHODS:
        raise ValueError("unsupported aggressor-side method")
    if str(provenance.get("aggressor_side_method") or "NONE") != method:
        raise ValueError("CME FX manifest and payload aggressor-side methods must match")
    rows = payload.get("bars")
    if not isinstance(rows, list) or not rows:
        raise ValueError("CME FX payload requires at least one completed bar")

    previous_end = ""
    has_open_interest = True
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not REQUIRED_BAR_FIELDS.issubset(row):
            raise ValueError(f"CME FX bar {index} is missing required fields")
        start = _utc(row["window_start_utc"], f"bars[{index}].window_start_utc")
        end = _utc(row["window_end_utc"], f"bars[{index}].window_end_utc")
        if end <= start or (previous_end and start < previous_end):
            raise ValueError("CME FX bars must be ordered, non-overlapping, and forward in time")
        previous_end = end
        prices = [_finite_nonnegative(row[name], f"bars[{index}].{name}") for name in ("open", "high", "low", "close")]
        if prices[1] < max(prices[0], prices[2], prices[3]) or prices[2] > min(prices[0], prices[1], prices[3]):
            raise ValueError(f"CME FX bar {index} has invalid OHLC geometry")
        volume = _finite_nonnegative(row["volume"], f"bars[{index}].volume")
        _finite_nonnegative(row["trade_count"], f"bars[{index}].trade_count")
        has_open_interest = has_open_interest and row.get("open_interest") is not None
        buy = row.get("aggressive_buy_volume")
        sell = row.get("aggressive_sell_volume")
        if method == "NONE":
            if buy is not None or sell is not None:
                raise ValueError("aggressor volumes require a declared classification method")
        else:
            buy_value = _finite_nonnegative(buy, f"bars[{index}].aggressive_buy_volume")
            sell_value = _finite_nonnegative(sell, f"bars[{index}].aggressive_sell_volume")
            if not math.isclose(buy_value + sell_value, volume, rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError("aggressive buy and sell volume must sum to total volume")
        if row.get("open_interest") is not None:
            _finite_nonnegative(row["open_interest"], f"bars[{index}].open_interest")

    classes = {str(value) for value in manifest.get("data_classes", [])}
    if "CME_FX_TRADES" not in classes:
        raise ValueError("CME FX bar payload must declare CME_FX_TRADES")
    if "CME_FX_AGGRESSOR_IMBALANCE" in classes and method == "NONE":
        raise ValueError("aggressor imbalance cannot be declared without classified centralized volume")
    if method != "NONE" and "CME_FX_AGGRESSOR_IMBALANCE" not in classes:
        raise ValueError("classified aggressor volume must declare CME_FX_AGGRESSOR_IMBALANCE")
    if "CME_FX_OPEN_INTEREST" in classes and not has_open_interest:
        raise ValueError("open-interest data class requires open interest on every bar")
    return payload


def package_csv_export(
    csv_path: Path,
    output_dir: Path,
    *,
    product: str,
    provider: str,
    source_symbol: str,
    contract_mode: str,
    roll_method: str,
    price_adjustment: str,
    aggressor_side_method: str = "NONE",
    freshness_status: str = "FRESH",
    gap_status: str = "COMPLETE",
) -> dict[str, Any]:
    if product not in SUPPORTED_PRODUCTS:
        raise ValueError(f"unsupported CME FX product: {product}")
    rows: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            row: dict[str, Any] = {
                key: source.get(key) for key in REQUIRED_BAR_FIELDS
            }
            for key in ("open_interest", "aggressive_buy_volume", "aggressive_sell_volume"):
                if source.get(key) not in (None, ""):
                    row[key] = source[key]
            rows.append(row)
    if not rows:
        raise ValueError("CME FX CSV has no data rows")

    payload = {
        "schema": "CME_FX_CONTEXT_EXPORT_V1",
        "canonical_product": product,
        "source_provider": provider,
        "source_symbol": source_symbol,
        "aggressor_side_method": aggressor_side_method,
        "contract_metadata": {
            "contract_mode": contract_mode,
            "roll_method": roll_method,
            "price_adjustment": price_adjustment,
        },
        "bars": rows,
    }
    data_classes = ["CME_FX_TRADES"]
    if aggressor_side_method != "NONE":
        data_classes.append("CME_FX_AGGRESSOR_IMBALANCE")
    if all(row.get("open_interest") is not None for row in rows):
        data_classes.append("CME_FX_OPEN_INTEREST")

    provider_provenance = {
        "provider": provider,
        "source_symbol": source_symbol,
        "canonical_product": product,
        "aggressor_side_method": aggressor_side_method,
    }
    provisional = {
        "instrument": product,
        "data_classes": data_classes,
        "provider_provenance": provider_provenance,
    }
    validate_futures_payload(provisional, payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    payload_digest = hashlib.sha256(canonical).hexdigest()
    stem = f"cme_{product.lower()}_{rows[0]['window_start_utc'][:10]}_{rows[-1]['window_end_utc'][:10]}_{payload_digest[:12]}"
    payload_path = output_dir / f"{stem}.payload.json.gz"
    with payload_path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as gzip_handle:
            gzip_handle.write(canonical)
    file_digest = hashlib.sha256(payload_path.read_bytes()).hexdigest()
    manifest = {
        "manifest_id": f"CME_FX_{product}_{payload_digest[:20].upper()}",
        "schema": "FX_MARKET_DATA_EXPORT_V1",
        "created_at_utc": rows[-1]["window_end_utc"],
        "source_system": "CME_FX_PROVIDER_EXPORT",
        "instrument": product,
        "window_start_utc": rows[0]["window_start_utc"],
        "window_end_utc": rows[-1]["window_end_utc"],
        "payload_sha256": file_digest,
        "payload_path": payload_path.name,
        "freshness_status": freshness_status,
        "gap_status": gap_status,
        "data_classes": data_classes,
        "row_counts": {"completed_futures_bars": len(rows)},
        "provider_provenance": provider_provenance,
    }
    manifest_path = output_dir / f"{stem}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"manifest_path": str(manifest_path), "payload_path": str(payload_path), "manifest": manifest}


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("schema") != "CME_FX_CONTEXT_CONTRACT_V1":
        raise ValueError("unsupported CME FX context contract")
    products = contract.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("CME FX context contract requires products")
    for product in products:
        if not isinstance(product, dict) or not product.get("canonical_product") or not product.get("spot_instrument"):
            raise ValueError("CME FX context products require canonical_product and spot_instrument")
    authority = contract.get("authority") if isinstance(contract.get("authority"), dict) else {}
    if authority.get("execution_authority") is not False or authority.get("context_only") is not True:
        raise ValueError("CME FX context must remain context-only without execution authority")
    phases = contract.get("activation_phases", [])
    if not isinstance(phases, list) or not phases:
        raise ValueError("CME FX context contract requires activation phases")
    phase_ids = set()
    for phase in phases:
        if not isinstance(phase, dict) or not phase.get("phase_id"):
            raise ValueError("CME FX activation phases require phase_id")
        phase_ids.add(str(phase["phase_id"]))
        if not phase.get("required_products") or not phase.get("required_data_classes"):
            raise ValueError("CME FX activation phases require products and data classes")
    if contract.get("primary_phase_id") not in phase_ids:
        raise ValueError("CME FX primary phase must name a declared activation phase")
    return contract


def futures_context_status(connection, contract_path: Path) -> dict[str, Any]:
    contract = load_contract(contract_path)
    available: dict[str, set[str]] = {}
    manifest_ids = []
    for row in connection.execute(
        "SELECT manifest_id, payload_json FROM market_data_manifests WHERE usable_for_testing=1 ORDER BY manifest_id"
    ).fetchall():
        manifest = json.loads(row["payload_json"])
        classes = {str(value) for value in manifest.get("data_classes", [])}
        futures_classes = classes & FUTURES_DATA_CLASSES
        if not futures_classes:
            continue
        product = str(manifest.get("instrument") or "UNKNOWN")
        provenance = manifest.get("provider_provenance") if isinstance(manifest.get("provider_provenance"), dict) else {}
        if "CME_FX_AGGRESSOR_IMBALANCE" in futures_classes and provenance.get("aggressor_side_method") in (None, "NONE"):
            futures_classes.remove("CME_FX_AGGRESSOR_IMBALANCE")
        available.setdefault(product, set()).update(futures_classes)
        manifest_ids.append(str(row["manifest_id"]))
    required_products = [str(value["canonical_product"]) for value in contract["products"]]
    missing_products = [value for value in required_products if value not in available]
    phases = []
    for phase in contract["activation_phases"]:
        phase_products = [str(value) for value in phase["required_products"]]
        phase_classes = {str(value) for value in phase["required_data_classes"]}
        missing_by_product = {
            product: sorted(phase_classes - available.get(product, set()))
            for product in phase_products
            if phase_classes - available.get(product, set())
        }
        phases.append({
            "phase_id": str(phase["phase_id"]),
            "status": "READY" if not missing_by_product else "UNCONFIGURED",
            "required_products": phase_products,
            "required_data_classes": sorted(phase_classes),
            "missing_data_classes_by_product": missing_by_product,
        })
    primary_phase = next(value for value in phases if value["phase_id"] == contract["primary_phase_id"])
    true_cvd_ready = any("CME_FX_AGGRESSOR_IMBALANCE" in values for values in available.values())
    return {
        "schema": "CME_FX_CONTEXT_STATUS_V1",
        "context_status": primary_phase["status"],
        "primary_phase_id": contract["primary_phase_id"],
        "activation_phases": phases,
        "full_product_coverage_status": "READY" if not missing_products else "UNCONFIGURED",
        "provider_configured": bool(available),
        "required_products": required_products,
        "available_data_classes_by_product": {
            key: sorted(values) for key, values in sorted(available.items())
        },
        "missing_products": missing_products,
        "manifest_ids": manifest_ids,
        "true_cvd_ready": true_cvd_ready,
        "cvd_disclosure": "TRUE_CVD_REQUIRES_CENTRALIZED_AGGRESSOR_SIDE_TRADE_DATA",
        "fallback_spot_proxy_is_not_true_cvd": True,
        "automatic_signal_or_execution_authority": False,
    }
