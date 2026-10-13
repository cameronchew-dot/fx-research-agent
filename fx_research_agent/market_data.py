from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import insert_immutable


PROHIBITED_KEYS = {
    "account_id",
    "account_name",
    "balance",
    "credentials",
    "order",
    "position",
    "token",
    "transaction",
}

REQUIRED_FIELDS = {
    "manifest_id",
    "schema",
    "created_at_utc",
    "source_system",
    "instrument",
    "window_start_utc",
    "window_end_utc",
    "payload_sha256",
    "payload_path",
    "freshness_status",
    "gap_status",
}


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).lower())
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_FIELDS - set(manifest))
    if missing:
        raise ValueError(f"market manifest missing fields: {missing}")
    prohibited = sorted(_walk_keys(manifest) & PROHIBITED_KEYS)
    if prohibited:
        raise ValueError(f"market manifest contains prohibited fields: {prohibited}")
    if manifest["schema"] != "FX_MARKET_DATA_EXPORT_V1":
        raise ValueError("unsupported market data export schema")

    payload_path = Path(manifest["payload_path"])
    if not payload_path.is_absolute():
        payload_path = manifest_path.parent / payload_path
    if not payload_path.is_file():
        raise ValueError("market export payload is missing")
    digest = hashlib.sha256(payload_path.read_bytes()).hexdigest()
    if digest != manifest["payload_sha256"]:
        raise ValueError("market export payload checksum mismatch")

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    prohibited_payload = sorted(_walk_keys(payload) & PROHIBITED_KEYS)
    if prohibited_payload:
        raise ValueError(f"market payload contains prohibited fields: {prohibited_payload}")
    return manifest


def register_manifest(connection, manifest_path: Path) -> dict[str, Any]:
    manifest = validate_manifest(manifest_path)
    usable = manifest["freshness_status"] == "FRESH" and manifest["gap_status"] == "COMPLETE"
    inserted = insert_immutable(
        connection,
        "market_data_manifests",
        "manifest_id",
        manifest["manifest_id"],
        manifest,
        {
            "registered_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "usable_for_testing": int(usable),
        },
    )
    return {"inserted": inserted, "usable_for_testing": usable, "manifest_id": manifest["manifest_id"]}

