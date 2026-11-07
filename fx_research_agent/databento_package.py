from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .futures_context import SUPPORTED_PRODUCTS
from .market_data import validate_manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iso_from_ns(value: Any) -> str:
    return datetime.fromtimestamp(int(value) / 1_000_000_000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def verify_source_package(source_dir: Path) -> dict[str, Any]:
    metadata_path = source_dir / "metadata.json"
    provider_manifest_path = source_dir / "manifest.json"
    condition_path = source_dir / "condition.json"
    for path in (metadata_path, provider_manifest_path, condition_path):
        if not path.is_file():
            raise ValueError(f"Databento package is missing {path.name}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    provider_manifest = json.loads(provider_manifest_path.read_text(encoding="utf-8"))
    conditions = json.loads(condition_path.read_text(encoding="utf-8"))
    query = metadata.get("query") if isinstance(metadata.get("query"), dict) else {}
    if query.get("dataset") != "GLBX.MDP3" or query.get("encoding") != "dbn" or query.get("compression") != "zstd":
        raise ValueError("Databento package must be GLBX.MDP3 DBN with zstd compression")
    symbols = query.get("symbols")
    if not isinstance(symbols, list) or len(symbols) != 1 or not str(symbols[0]).endswith(".FUT"):
        raise ValueError("Databento package must contain exactly one CME futures parent product")
    product = str(symbols[0]).removesuffix(".FUT")
    if product not in SUPPORTED_PRODUCTS:
        raise ValueError(f"unsupported CME FX product: {product}")
    if metadata.get("job_id") != provider_manifest.get("job_id"):
        raise ValueError("Databento metadata and manifest job IDs disagree")

    verified_files = []
    for item in provider_manifest.get("files", []):
        filename = str(item.get("filename") or "")
        source_file = (source_dir / filename).resolve()
        if not filename or source_file.parent != source_dir.resolve() or not source_file.is_file():
            raise ValueError("Databento manifest references a missing or unsafe path")
        expected_hash = str(item.get("hash") or "").removeprefix("sha256:")
        if source_file.stat().st_size != int(item.get("size") or -1) or sha256_file(source_file) != expected_hash:
            raise ValueError(f"Databento source integrity check failed: {filename}")
        if filename.endswith(".dbn.zst"):
            verified_files.append({"filename": filename, "size_bytes": source_file.stat().st_size, "sha256": expected_hash})
    if not verified_files:
        raise ValueError("Databento package contains no DBN source files")

    if not isinstance(conditions, list):
        raise ValueError("Databento condition file must contain date conditions")
    condition_counts = Counter(str(item.get("condition") or "UNKNOWN") for item in conditions if isinstance(item, dict))
    excluded_dates = sorted(
        str(item.get("date")) for item in conditions
        if isinstance(item, dict) and item.get("condition") != "available" and item.get("date")
    )
    return {
        "metadata": metadata,
        "provider_manifest": provider_manifest,
        "product": product,
        "source_schema": str(query.get("schema") or ""),
        "source_symbol": str(symbols[0]),
        "window_start_utc": iso_from_ns(query["start"]),
        "window_end_utc": iso_from_ns(query["end"]),
        "files": verified_files,
        "condition_counts": dict(sorted(condition_counts.items())),
        "excluded_dates": excluded_dates,
        "provider_manifest_sha256": sha256_file(provider_manifest_path),
    }


def import_package(source_dir: Path, output_root: Path) -> dict[str, Any]:
    verified = verify_source_package(source_dir)
    job_id = str(verified["metadata"]["job_id"])
    final_dir = output_root / job_id
    if final_dir.exists():
        existing_manifest = final_dir / f"{job_id}.market.manifest.json"
        if not existing_manifest.is_file():
            raise ValueError("existing Databento destination is incomplete")
        validate_manifest(existing_manifest)
        return {"status": "UNCHANGED", "package_dir": str(final_dir), "manifest_path": str(existing_manifest)}

    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{job_id}.", dir=output_root) as temp_name:
        temp_dir = Path(temp_name)
        for source_file in source_dir.iterdir():
            if source_file.is_file():
                shutil.copy2(source_file, temp_dir / source_file.name)
        payload = {
            "schema": "CME_FX_DATABENTO_PACKAGE_V1",
            "canonical_product": verified["product"],
            "source_provider": "DATABENTO",
            "source_dataset": "GLBX.MDP3",
            "source_schema": verified["source_schema"],
            "source_symbol": verified["source_symbol"],
            "source_job_id": job_id,
            "source_manifest_sha256": verified["provider_manifest_sha256"],
            "window_start_utc": verified["window_start_utc"],
            "window_end_utc": verified["window_end_utc"],
            "files": verified["files"],
            "quality": {
                "source_condition_counts": verified["condition_counts"],
                "excluded_dates": verified["excluded_dates"],
                "exclusion_policy": "EXCLUDE_NON_AVAILABLE_SOURCE_DATES",
            },
        }
        payload_path = temp_dir / f"{job_id}.package-index.payload.json"
        payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload_digest = sha256_file(payload_path)
        source_schema = verified["source_schema"]
        data_class = "CME_FX_BARS" if source_schema.startswith("ohlcv-") else "CME_FX_TRADES"
        provider_provenance = {
            "provider": "DATABENTO",
            "source_dataset": "GLBX.MDP3",
            "source_symbol": verified["source_symbol"],
            "source_job_id": job_id,
            "aggressor_side_method": "NONE",
        }
        manifest = {
            "manifest_id": f"DATABENTO_{job_id}",
            "schema": "FX_MARKET_DATA_EXPORT_V1",
            "created_at_utc": verified["window_end_utc"],
            "source_system": "DATABENTO_BATCH_EXPORT",
            "instrument": verified["product"],
            "window_start_utc": verified["window_start_utc"],
            "window_end_utc": verified["window_end_utc"],
            "payload_sha256": payload_digest,
            "payload_path": payload_path.name,
            "freshness_status": "FRESH",
            "gap_status": "COMPLETE_WITH_DECLARED_EXCLUSIONS" if verified["excluded_dates"] else "COMPLETE",
            "data_classes": [data_class],
            "row_counts": {"provider_source_files": len(verified["files"])},
            "provider_provenance": provider_provenance,
        }
        manifest_path = temp_dir / f"{job_id}.market.manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_manifest(manifest_path)
        temp_dir.replace(final_dir)
    final_manifest = final_dir / f"{job_id}.market.manifest.json"
    return {
        "status": "IMPORTED",
        "package_dir": str(final_dir),
        "manifest_path": str(final_manifest),
        "excluded_date_count": len(verified["excluded_dates"]),
        "source_file_count": len(verified["files"]),
    }
