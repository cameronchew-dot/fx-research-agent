from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import canonical_json, insert_immutable


PROHIBITED_KEYS = {
    "account_id", "account_name", "balance", "balances", "credential", "credentials",
    "order", "orders", "position", "positions", "token", "tokens", "transaction", "transactions",
}
REQUIRED_MANIFEST_FIELDS = {
    "schema", "package_id", "created_at_utc", "source_system", "source_repo", "source_commit",
    "payload_path", "payload_sha256", "content_sha256", "result_count", "authority",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _payload_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    path = Path(str(manifest["payload_path"]))
    return path if path.is_absolute() else manifest_path.parent / path


def _read_payload(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("research result payload must be an object")
    return payload


def validate_package(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_MANIFEST_FIELDS - set(manifest))
    if missing:
        raise ValueError(f"research result manifest missing fields: {missing}")
    if manifest.get("schema") != "FX_RESEARCH_RESULT_MANIFEST_V1":
        raise ValueError("unsupported research result manifest schema")
    authority = manifest.get("authority") if isinstance(manifest.get("authority"), dict) else {}
    if authority != {
        "research_only": True,
        "automatic_promotion": False,
        "order_authority": False,
        "downstream_activation": False,
    }:
        raise ValueError("research result package authority must be inert")
    prohibited = sorted(_walk_keys(manifest) & PROHIBITED_KEYS)
    if prohibited:
        raise ValueError(f"research result manifest contains prohibited fields: {prohibited}")
    payload_path = _payload_path(manifest_path, manifest)
    if not payload_path.is_file():
        raise ValueError("research result payload is missing")
    if hashlib.sha256(payload_path.read_bytes()).hexdigest() != manifest["payload_sha256"]:
        raise ValueError("research result payload checksum mismatch")
    payload = _read_payload(payload_path)
    if payload.get("schema") != "FX_RESEARCH_RESULT_PAYLOAD_V1":
        raise ValueError("unsupported research result payload schema")
    if payload.get("package_id") != manifest["package_id"]:
        raise ValueError("research result package id mismatch")
    core = {key: value for key, value in payload.items() if key not in {"package_id", "content_sha256"}}
    content_sha = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
    if content_sha != manifest["content_sha256"] or content_sha != payload.get("content_sha256"):
        raise ValueError("research result content checksum mismatch")
    prohibited = sorted(_walk_keys(payload) & PROHIBITED_KEYS)
    if prohibited:
        raise ValueError(f"research result payload contains prohibited fields: {prohibited}")
    records = payload.get("result_records")
    if not isinstance(records, list) or len(records) != int(manifest["result_count"]):
        raise ValueError("research result count mismatch")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or record.get("schema") != "FX_EXTERNAL_RESEARCH_RESULT_V1":
            raise ValueError("invalid external research result record")
        required = {"result_id", "hypothesis_id", "instrument", "result_status", "knowable_at_utc", "safety"}
        if required - set(record):
            raise ValueError("external research result record is incomplete")
        result_id = str(record["result_id"])
        if result_id in seen:
            raise ValueError(f"duplicate external research result id: {result_id}")
        seen.add(result_id)
        safety = record.get("safety") if isinstance(record.get("safety"), dict) else {}
        if safety.get("research_only") is not True or safety.get("downstream_authority") != "NONE":
            raise ValueError("external research result record claims downstream authority")
    return manifest, payload


def register_package(connection, manifest_path: Path, *, imported_at_utc: str | None = None) -> dict[str, Any]:
    manifest, payload = validate_package(manifest_path)
    imported_at = imported_at_utc or utc_now()
    connection.execute("SAVEPOINT register_external_result_package")
    try:
        package_inserted = insert_immutable(
            connection,
            "external_result_manifests",
            "package_id",
            str(manifest["package_id"]),
            manifest,
            {"imported_at_utc": imported_at},
        )
        counts = {"inserted": 0, "unchanged": 0}
        for record in payload["result_records"]:
            inserted = insert_immutable(
                connection,
                "external_research_results",
                "result_id",
                str(record["result_id"]),
                record,
                {
                    "package_id": manifest["package_id"],
                    "hypothesis_id": record["hypothesis_id"],
                    "instrument": record["instrument"],
                    "result_status": record["result_status"],
                    "knowable_at_utc": record["knowable_at_utc"],
                    "imported_at_utc": imported_at,
                },
            )
            counts["inserted" if inserted else "unchanged"] += 1
    except Exception:
        connection.execute("ROLLBACK TO register_external_result_package")
        connection.execute("RELEASE register_external_result_package")
        raise
    connection.execute("RELEASE register_external_result_package")
    return {"package_id": manifest["package_id"], "package_inserted": package_inserted, **counts}


def sync_packages(connection, source_dir: Path, inbox_dir: Path) -> dict[str, Any]:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"manifest_count": 0, "inserted": 0, "unchanged": 0, "rejected": []}
    for source_manifest in sorted(source_dir.glob("*.manifest.json")) if source_dir.exists() else []:
        summary["manifest_count"] += 1
        try:
            manifest, _ = validate_package(source_manifest)
            source_payload = _payload_path(source_manifest, manifest)
            local_manifest = inbox_dir / source_manifest.name
            local_payload = inbox_dir / source_payload.name
            if local_manifest.exists() and local_manifest.read_bytes() != source_manifest.read_bytes():
                raise ValueError("conflicting local research result manifest rewrite")
            if local_payload.exists() and local_payload.read_bytes() != source_payload.read_bytes():
                raise ValueError("conflicting local research result payload rewrite")
            if not local_payload.exists():
                shutil.copy2(source_payload, local_payload)
            if not local_manifest.exists():
                shutil.copy2(source_manifest, local_manifest)
            result = register_package(connection, local_manifest)
            summary["inserted"] += int(result["inserted"])
            summary["unchanged"] += int(result["unchanged"])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            summary["rejected"].append({"manifest": str(source_manifest), "error": str(exc)})
    summary["sync_status"] = "OK" if not summary["rejected"] else "PARTIAL"
    return summary


def result_status(connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT instrument, result_status, payload_json FROM external_research_results ORDER BY knowable_at_utc, result_id"
    ).fetchall()
    by_instrument: dict[str, int] = {}
    by_status: dict[str, int] = {}
    records = []
    for row in rows:
        by_instrument[str(row["instrument"])] = by_instrument.get(str(row["instrument"]), 0) + 1
        by_status[str(row["result_status"])] = by_status.get(str(row["result_status"]), 0) + 1
        records.append(json.loads(row["payload_json"]))
    return {
        "research_result_status": "READY" if rows else "EMPTY",
        "result_count": len(rows),
        "by_instrument": dict(sorted(by_instrument.items())),
        "by_result_status": dict(sorted(by_status.items())),
        "results": records,
        "automatic_promotion_allowed": False,
        "downstream_authority": "NONE",
    }
