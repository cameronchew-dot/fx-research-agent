from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FUTURES_DATA_CLASSES = {
    "CME_FX_TRADES",
    "CME_FX_AGGRESSOR_IMBALANCE",
    "CME_FX_ORDER_BOOK",
    "CME_FX_OPEN_INTEREST",
    "CME_SPOT_BASIS",
}


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
        available.setdefault(product, set()).update(futures_classes)
        manifest_ids.append(str(row["manifest_id"]))
    required_products = [str(value["canonical_product"]) for value in contract["products"]]
    missing_products = [value for value in required_products if value not in available]
    true_cvd_ready = any("CME_FX_AGGRESSOR_IMBALANCE" in values for values in available.values())
    return {
        "schema": "CME_FX_CONTEXT_STATUS_V1",
        "context_status": "READY" if not missing_products else "UNCONFIGURED",
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
