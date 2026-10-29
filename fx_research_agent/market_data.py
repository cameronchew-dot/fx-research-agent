from __future__ import annotations

import hashlib
import gzip
import json
import shutil
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
    "accounts",
    "balances",
    "orders",
    "positions",
    "tokens",
    "transactions",
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

    if payload_path.suffix == ".gz":
        with gzip.open(payload_path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    prohibited_payload = sorted(_walk_keys(payload) & PROHIBITED_KEYS)
    if prohibited_payload:
        raise ValueError(f"market payload contains prohibited fields: {prohibited_payload}")
    data_classes = {str(value) for value in manifest.get("data_classes", [])}
    if data_classes & {
        "COMPLETED_DAILY_BID_ASK_CANDLES",
        "MONTHLY_FINANCING_OR_FORWARD_POINTS",
        "CURRENCY_EXCESS_RETURNS",
    }:
        from .literature_panels import validate_panel_payload

        validate_panel_payload(manifest, payload)
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


def resolve_payload_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    payload_path = Path(manifest["payload_path"])
    return payload_path if payload_path.is_absolute() else manifest_path.parent / payload_path


def sync_market_exports(connection, source_dir: Path, inbox_dir: Path) -> dict[str, Any]:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "source_dir": str(source_dir),
        "inbox_dir": str(inbox_dir),
        "manifest_count": 0,
        "inserted_count": 0,
        "unchanged_count": 0,
        "usable_count": 0,
        "rejected": [],
    }
    for manifest_path in sorted(source_dir.glob("*.manifest.json")) if source_dir.exists() else []:
        summary["manifest_count"] += 1
        try:
            source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            local_manifest = inbox_dir / manifest_path.name
            if local_manifest.exists():
                existing = json.loads(local_manifest.read_text(encoding="utf-8"))
                if existing != source_manifest:
                    raise ValueError("conflicting local manifest rewrite")
                row = connection.execute(
                    "SELECT usable_for_testing FROM market_data_manifests WHERE manifest_id=?",
                    (source_manifest.get("manifest_id"),),
                ).fetchone()
                if row is None:
                    result = register_manifest(connection, local_manifest)
                    summary["inserted_count" if result["inserted"] else "unchanged_count"] += 1
                    summary["usable_count"] += int(result["usable_for_testing"])
                else:
                    summary["unchanged_count"] += 1
                    summary["usable_count"] += int(row["usable_for_testing"])
                continue

            manifest = validate_manifest(manifest_path)
            source_payload = resolve_payload_path(manifest_path, manifest)
            local_payload = inbox_dir / source_payload.name
            if local_payload.exists() and hashlib.sha256(local_payload.read_bytes()).hexdigest() != manifest["payload_sha256"]:
                raise ValueError("conflicting local payload for immutable manifest")
            if local_payload.exists():
                raise ValueError("orphaned local payload exists without its immutable manifest")
            else:
                shutil.copy2(source_payload, local_payload)
                shutil.copy2(manifest_path, local_manifest)
            result = register_manifest(connection, local_manifest)
            summary["inserted_count" if result["inserted"] else "unchanged_count"] += 1
            summary["usable_count"] += int(result["usable_for_testing"])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            summary["rejected"].append({"manifest": str(manifest_path), "error": str(exc)})
    summary["sync_status"] = "OK" if not summary["rejected"] else "PARTIAL"
    return summary


def market_data_status(connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT payload_json, usable_for_testing FROM market_data_manifests ORDER BY registered_at_utc"
    ).fetchall()
    instruments: dict[str, int] = {}
    data_classes_by_instrument: dict[str, set[str]] = {}
    windows_by_instrument: dict[str, dict[str, str | None]] = {}
    latest_window_end: str | None = None
    usable = 0
    stale = 0
    gapped = 0
    total_rows = 0
    for row in rows:
        manifest = json.loads(row["payload_json"])
        instrument = str(manifest.get("instrument") or "UNKNOWN")
        instruments[instrument] = instruments.get(instrument, 0) + 1
        data_classes_by_instrument.setdefault(instrument, set()).update(
            str(value) for value in manifest.get("data_classes", [])
        )
        window = windows_by_instrument.setdefault(instrument, {"start_utc": None, "end_utc": None})
        start = str(manifest.get("window_start_utc") or "")
        end = str(manifest.get("window_end_utc") or "")
        if start:
            window["start_utc"] = min(str(window["start_utc"] or start), start)
        if end:
            window["end_utc"] = max(str(window["end_utc"] or end), end)
        latest_window_end = max(latest_window_end or "", str(manifest.get("window_end_utc") or "")) or latest_window_end
        usable += int(row["usable_for_testing"])
        stale += int(manifest.get("freshness_status") != "FRESH")
        gapped += int(manifest.get("gap_status") != "COMPLETE")
        counts = manifest.get("row_counts") if isinstance(manifest.get("row_counts"), dict) else {}
        total_rows += sum(int(value) for value in counts.values() if isinstance(value, int))
    return {
        "market_data_status": "READY" if usable else "EMPTY_OR_BLOCKED",
        "manifest_count": len(rows),
        "usable_manifest_count": usable,
        "stale_manifest_count": stale,
        "gapped_manifest_count": gapped,
        "latest_window_end_utc": latest_window_end,
        "instruments": instruments,
        "data_classes_by_instrument": {
            instrument: sorted(values) for instrument, values in data_classes_by_instrument.items()
        },
        "windows_by_instrument": windows_by_instrument,
        "declared_row_count": total_rows,
        "cvd_disclosure": "OANDA_VENUE_TICK_PROXY_NOT_CENTRALIZED_FX_VOLUME",
    }

