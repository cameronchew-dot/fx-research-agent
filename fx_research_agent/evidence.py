from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import insert_immutable


MANIFEST_SCHEMA = "FX_RESEARCH_EVIDENCE_EXPORT_V1"
PAYLOAD_SCHEMA = "FX_RESEARCH_EVIDENCE_PAYLOAD_V1"
ALLOWED_DATA_CLASSES = {
    "OBJECTIVE_LEVELS",
    "FORWARD_FAILED_AUCTION_EPISODES",
    "FORWARD_RULE_BASELINE_OUTCOMES",
    "TREND_LOCATION_RANGE_CONTEXT",
}
PROHIBITED_KEY_FRAGMENTS = {
    "account",
    "balance",
    "broker",
    "credential",
    "memory",
    "order",
    "position",
    "prompt",
    "provider",
    "rationale",
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
    "data_classes",
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


def _prohibited_keys(value: Any) -> list[str]:
    return sorted(
        key
        for key in _walk_keys(value)
        if any(fragment in key for fragment in PROHIBITED_KEY_FRAGMENTS)
    )


def _read_payload(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("research evidence payload must be an object")
    return payload


def resolve_payload_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    payload_path = Path(manifest["payload_path"])
    return payload_path if payload_path.is_absolute() else manifest_path.parent / payload_path


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_FIELDS - set(manifest))
    if missing:
        raise ValueError(f"research evidence manifest missing fields: {missing}")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ValueError("unsupported research evidence export schema")
    prohibited = _prohibited_keys(manifest)
    if prohibited:
        raise ValueError(f"research evidence manifest contains prohibited fields: {prohibited}")
    data_classes = set(str(value) for value in manifest["data_classes"])
    unknown_classes = sorted(data_classes - ALLOWED_DATA_CLASSES)
    if unknown_classes:
        raise ValueError(f"research evidence contains unsupported data classes: {unknown_classes}")

    payload_path = resolve_payload_path(manifest_path, manifest)
    if not payload_path.is_file():
        raise ValueError("research evidence payload is missing")
    if hashlib.sha256(payload_path.read_bytes()).hexdigest() != manifest["payload_sha256"]:
        raise ValueError("research evidence payload checksum mismatch")
    payload = _read_payload(payload_path)
    if payload.get("schema") != PAYLOAD_SCHEMA:
        raise ValueError("unsupported research evidence payload schema")
    if payload.get("manifest_id") != manifest["manifest_id"]:
        raise ValueError("research evidence manifest and payload identities differ")
    if set(str(value) for value in payload.get("data_classes", [])) != data_classes:
        raise ValueError("research evidence data classes differ between manifest and payload")
    prohibited_payload = _prohibited_keys(payload)
    if prohibited_payload:
        raise ValueError(f"research evidence payload contains prohibited fields: {prohibited_payload}")
    return manifest


def load_validated_package(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = validate_manifest(manifest_path)
    return manifest, _read_payload(resolve_payload_path(manifest_path, manifest))


def register_manifest(connection, manifest_path: Path) -> dict[str, Any]:
    manifest = validate_manifest(manifest_path)
    usable = manifest["freshness_status"] == "FRESH" and manifest["gap_status"] == "COMPLETE"
    inserted = insert_immutable(
        connection,
        "evidence_manifests",
        "manifest_id",
        manifest["manifest_id"],
        manifest,
        {
            "registered_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "usable_for_testing": int(usable),
        },
    )
    return {"inserted": inserted, "usable_for_testing": usable, "manifest_id": manifest["manifest_id"]}


def sync_evidence_exports(connection, source_dir: Path, inbox_dir: Path) -> dict[str, Any]:
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
    manifests = sorted(source_dir.glob("*.manifest.json")) if source_dir.exists() else []
    for manifest_path in manifests:
        summary["manifest_count"] += 1
        try:
            source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            local_manifest = inbox_dir / manifest_path.name
            if local_manifest.exists():
                if json.loads(local_manifest.read_text(encoding="utf-8")) != source_manifest:
                    raise ValueError("conflicting local research evidence manifest rewrite")
                row = connection.execute(
                    "SELECT usable_for_testing FROM evidence_manifests WHERE manifest_id=?",
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
            if local_payload.exists():
                raise ValueError("orphaned local research evidence payload exists")
            shutil.copy2(source_payload, local_payload)
            shutil.copy2(manifest_path, local_manifest)
            result = register_manifest(connection, local_manifest)
            summary["inserted_count" if result["inserted"] else "unchanged_count"] += 1
            summary["usable_count"] += int(result["usable_for_testing"])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            summary["rejected"].append({"manifest": str(manifest_path), "error": str(exc)})
    summary["sync_status"] = "OK" if not summary["rejected"] else "PARTIAL"
    return summary


def evidence_status(connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT payload_json, usable_for_testing FROM evidence_manifests ORDER BY registered_at_utc"
    ).fetchall()
    available_classes: set[str] = set()
    latest_window_end: str | None = None
    usable = stale = gapped = total_rows = 0
    for row in rows:
        manifest = json.loads(row["payload_json"])
        if row["usable_for_testing"]:
            available_classes.update(str(value) for value in manifest.get("data_classes", []))
        latest_window_end = max(latest_window_end or "", str(manifest.get("window_end_utc") or "")) or latest_window_end
        usable += int(row["usable_for_testing"])
        stale += int(manifest.get("freshness_status") != "FRESH")
        gapped += int(manifest.get("gap_status") != "COMPLETE")
        counts = manifest.get("row_counts") if isinstance(manifest.get("row_counts"), dict) else {}
        total_rows += sum(int(value) for value in counts.values() if isinstance(value, int))
    return {
        "research_evidence_status": "READY" if usable else "EMPTY_OR_BLOCKED",
        "manifest_count": len(rows),
        "usable_manifest_count": usable,
        "stale_manifest_count": stale,
        "gapped_manifest_count": gapped,
        "latest_window_end_utc": latest_window_end,
        "available_data_classes": sorted(available_classes),
        "declared_row_count": total_rows,
        "authority": "RESEARCH_ONLY_NO_ORDER_OR_LIFECYCLE_AUTHORITY",
    }
