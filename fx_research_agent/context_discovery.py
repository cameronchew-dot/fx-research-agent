from __future__ import annotations

import gzip
import hashlib
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .market_data import validate_manifest
from .motif_discovery import _kmeans, sha256_file, write_json_atomic
from .storage import canonical_json, insert_immutable, payload_hash


CONTRACT_SCHEMA = "FX_CONTEXT_DISCOVERY_CONTRACT_V1"
AUDIT_SCHEMA = "FX_CONTEXT_COVERAGE_AUDIT_V1"
MATRIX_SCHEMA = "FX_CONTEXT_FEATURE_MATRIX_V1"
REPORT_SCHEMA = "FX_CONTEXT_DISCOVERY_REPORT_V1"
MATRIX_BUILDER_VERSION = "1.0.0"
DISCOVERY_RUNNER_VERSION = "1.0.0"
FORBIDDEN_FEATURE_TOKENS = (
    "outcome", "forward", "target", "terminal", "mfe", "mae", "pnl", "net_r",
    "strategy", "family", "candidate", "signal", "label",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_payload(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("unsupported context discovery contract")
    sources = payload.get("required_sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("context discovery requires at least one source")
    identities = [(str(row.get("instrument")), str(row.get("granularity"))) for row in sources]
    if len(identities) != len(set(identities)):
        raise ValueError("context discovery source identities must be unique")
    features = payload.get("feature_names")
    if not isinstance(features, list) or not features or len(features) != len(set(features)):
        raise ValueError("context discovery feature names must be unique and non-empty")
    offending = [name for name in features if any(token in str(name).lower() for token in FORBIDDEN_FEATURE_TOKENS)]
    if offending:
        raise ValueError(f"future/strategy-derived context features are forbidden: {offending}")
    if payload.get("future_outcomes_allowed_in_features") is not False:
        raise ValueError("context discovery must exclude future outcomes")
    authority = payload.get("authority") if isinstance(payload.get("authority"), dict) else {}
    if authority.get("research_only") is not True or authority.get("paper_or_live_authority") is not False:
        raise ValueError("context discovery must remain research-only")
    return payload


def _registered_manifests(connection, instrument: str, data_class: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    rows = connection.execute(
        "SELECT payload_json, usable_for_testing FROM market_data_manifests ORDER BY registered_at_utc"
    ).fetchall()
    for row in rows:
        manifest = json.loads(row["payload_json"])
        if not int(row["usable_for_testing"]):
            continue
        if manifest.get("instrument") != instrument:
            continue
        if data_class not in set(manifest.get("data_classes") or []):
            continue
        output.append(manifest)
    return output


def audit_context_coverage(
    connection,
    *,
    contract_path: Path,
    inbox_dir: Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    created = created_at_utc or utc_now()
    development = contract["development"]
    start = str(development["start_utc"])
    end = str(development["end_utc_exclusive"])
    source_results: list[dict[str, Any]] = []

    for source in contract["required_sources"]:
        instrument = str(source["instrument"])
        granularity = str(source["granularity"])
        data_class = str(source.get("source_data_class") or "HISTORICAL_COMPLETED_CANDLES")
        manifests = _registered_manifests(connection, instrument, data_class)
        candles: dict[str, dict[str, Any]] = {}
        source_lineage: list[dict[str, Any]] = []
        for manifest in manifests:
            manifest_path = inbox_dir / f"{manifest['manifest_id']}.manifest.json"
            if not manifest_path.is_file():
                raise ValueError(f"registered context manifest missing from inbox: {manifest['manifest_id']}")
            validated = validate_manifest(manifest_path)
            payload_path = inbox_dir / str(validated["payload_path"])
            payload = _load_payload(payload_path)
            if payload.get("schema") != "FX_HISTORICAL_MARKET_DATA_PAYLOAD_V1":
                raise ValueError("context discovery requires sealed historical candle payloads")
            quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
            if quality.get("future_outcomes_exported") is not False or quality.get("strategy_labels_exported") is not False:
                raise ValueError("context source does not prove outcome/label exclusion")
            for candle in payload.get("completed_candles") or []:
                if candle.get("instrument") != instrument or candle.get("granularity") != granularity:
                    continue
                time_utc = str(candle.get("candle_time_utc") or "")
                if not start <= time_utc < end:
                    continue
                existing = candles.get(time_utc)
                if existing is not None and canonical_json(existing) != canonical_json(candle):
                    raise ValueError(f"conflicting historical context candle rewrite: {(instrument, granularity, time_utc)}")
                candles[time_utc] = candle
            source_lineage.append(
                {
                    "manifest_id": manifest["manifest_id"],
                    "payload_sha256": manifest["payload_sha256"],
                    "window_start_utc": manifest["window_start_utc"],
                    "window_end_utc": manifest["window_end_utc"],
                }
            )
        ordered_times = sorted(candles)
        distinct_days = len({value[:10] for value in ordered_times})
        minimum_rows = int(source["minimum_development_rows"])
        minimum_days = int(source.get("minimum_distinct_days") or 0)
        blocks: list[str] = []
        if len(ordered_times) < minimum_rows:
            blocks.append("development_row_count_below_minimum")
        if distinct_days < minimum_days:
            blocks.append("development_distinct_days_below_minimum")
        if not source_lineage:
            blocks.append("sealed_source_manifest_missing")
        source_results.append(
            {
                "source_id": source["source_id"],
                "role": source["role"],
                "instrument": instrument,
                "granularity": granularity,
                "development_row_count": len(ordered_times),
                "development_distinct_day_count": distinct_days,
                "first_development_candle_utc": ordered_times[0] if ordered_times else None,
                "last_development_candle_utc": ordered_times[-1] if ordered_times else None,
                "minimum_development_rows": minimum_rows,
                "minimum_distinct_days": minimum_days,
                "status": "PASS" if not blocks else "BLOCKED",
                "blocks": blocks,
                "source_lineage": source_lineage,
            }
        )

    blocked = [row["source_id"] for row in source_results if row["status"] != "PASS"]
    identity = {
        "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "sources": [
            {
                "source_id": row["source_id"],
                "lineage": row["source_lineage"],
                "rows": row["development_row_count"],
            }
            for row in source_results
        ],
    }
    audit_id = "FX_CONTEXT_COVERAGE_" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:20]
    existing = connection.execute(
        "SELECT payload_json FROM context_coverage_audits WHERE audit_id=?",
        (audit_id,),
    ).fetchone()
    if existing is not None:
        return json.loads(existing["payload_json"])
    report = {
        "schema": AUDIT_SCHEMA,
        "audit_id": audit_id,
        "created_at_utc": created,
        "contract_id": contract["contract_id"],
        "contract_sha256": identity["contract_sha256"],
        "coverage_status": "READY_FOR_OUTCOME_BLIND_CONTEXT_DISCOVERY" if not blocked else "BLOCKED_DATA_COVERAGE",
        "development": development,
        "source_results": source_results,
        "blocked_source_ids": blocked,
        "excluded_sources": contract.get("excluded_sources") or [],
        "safety": {
            "future_outcomes_read": False,
            "strategy_labels_read": False,
            "validation_or_holdout_outcomes_read": False,
            "campaign_created": False,
            "downstream_export_created": False,
            "paper_or_live_authority": False,
        },
    }
    insert_immutable(
        connection,
        "context_coverage_audits",
        "audit_id",
        audit_id,
        report,
        {"created_at_utc": created},
    )
    return report


def _parse_utc(value: Any) -> float:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def _load_context_rows(
    connection,
    inbox_dir: Path,
    contract: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    start = str(contract["development"]["start_utc"])
    end = str(contract["development"]["end_utc_exclusive"])
    grouped: dict[str, list[dict[str, Any]]] = {}
    lineage: list[dict[str, Any]] = []
    for source in contract["required_sources"]:
        instrument = str(source["instrument"])
        granularity = str(source["granularity"])
        data_class = str(source.get("source_data_class") or "HISTORICAL_COMPLETED_CANDLES")
        candles: dict[str, dict[str, Any]] = {}
        manifests = _registered_manifests(connection, instrument, data_class)
        for manifest in manifests:
            manifest_path = inbox_dir / f"{manifest['manifest_id']}.manifest.json"
            if not manifest_path.is_file():
                raise ValueError(f"registered context manifest missing from inbox: {manifest['manifest_id']}")
            validated = validate_manifest(manifest_path)
            payload = _load_payload(inbox_dir / str(validated["payload_path"]))
            quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
            if payload.get("schema") != "FX_HISTORICAL_MARKET_DATA_PAYLOAD_V1":
                raise ValueError("context discovery requires sealed historical candle payloads")
            if quality.get("future_outcomes_exported") is not False or quality.get("strategy_labels_exported") is not False:
                raise ValueError("context source does not prove outcome/label exclusion")
            for candle in payload.get("completed_candles") or []:
                if candle.get("instrument") != instrument or candle.get("granularity") != granularity:
                    continue
                time_utc = str(candle.get("candle_time_utc") or "")
                if not start <= time_utc < end:
                    continue
                existing = candles.get(time_utc)
                if existing is not None and canonical_json(existing) != canonical_json(candle):
                    raise ValueError(f"conflicting historical context candle rewrite: {(instrument, granularity, time_utc)}")
                candles[time_utc] = candle
            lineage.append(
                {
                    "source_id": source["source_id"],
                    "manifest_id": manifest["manifest_id"],
                    "payload_sha256": manifest["payload_sha256"],
                    "window_start_utc": manifest["window_start_utc"],
                    "window_end_utc": manifest["window_end_utc"],
                }
            )
        grouped[str(source["source_id"])] = [candles[key] for key in sorted(candles)]
    return grouped, lineage


def _source_pack(rows: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    close = np.asarray([float(row["close"]) for row in rows], dtype=np.float64)
    end = np.asarray(
        [_parse_utc(row.get("candle_end_time_utc") or row["candle_time_utc"]) for row in rows],
        dtype=np.float64,
    )
    return {"close": close, "end": end}


def _asof(pack: dict[str, np.ndarray], decision_time: float) -> int:
    return int(np.searchsorted(pack["end"], decision_time, side="right")) - 1


def _log_return(pack: dict[str, np.ndarray], index: int, lag: int) -> float:
    if index < lag:
        return math.nan
    current = float(pack["close"][index])
    previous = float(pack["close"][index - lag])
    return math.log(current / previous) if current > 0 and previous > 0 else math.nan


def _session_features(decision_time: float) -> dict[str, float]:
    hour = datetime.fromtimestamp(decision_time, tz=timezone.utc).hour
    active = (
        "session_asia" if hour < 7 else
        "session_london" if hour < 12 else
        "session_london_ny_overlap" if hour < 16 else
        "session_ny_afternoon" if hour < 21 else
        "session_rollover_late"
    )
    names = (
        "session_asia", "session_london", "session_london_ny_overlap",
        "session_ny_afternoon", "session_rollover_late",
    )
    return {name: float(name == active) for name in names}


def build_context_feature_arrays(
    source_rows: dict[str, list[dict[str, Any]]],
    contract: dict[str, Any],
) -> dict[str, np.ndarray]:
    packs = {source_id: _source_pack(rows) for source_id, rows in source_rows.items()}
    primary = packs["EURUSD_M15"]
    feature_names = [str(value) for value in contract["feature_names"]]
    rows: list[list[float]] = []
    times: list[str] = []
    context_sources = (
        "EURGBP_M15", "EURJPY_M15", "XAUUSD_M15", "SPX500_H1",
        "NAS100_H1", "USB10Y_H1", "DE10YB_H1",
    )
    for primary_index in range(4, len(primary["close"])):
        decision_time = float(primary["end"][primary_index])
        indices = {source_id: _asof(packs[source_id], decision_time) for source_id in context_sources}
        if min(indices.values()) < 4:
            continue
        returns: dict[str, float] = {}
        for source_id in context_sources:
            prefix = {
                "EURGBP_M15": "eurgbp", "EURJPY_M15": "eurjpy", "XAUUSD_M15": "xauusd",
                "SPX500_H1": "spx500", "NAS100_H1": "nas100", "USB10Y_H1": "usb10y",
                "DE10YB_H1": "de10yb",
            }[source_id]
            returns[f"{prefix}_return_1"] = _log_return(packs[source_id], indices[source_id], 1)
            returns[f"{prefix}_return_4"] = _log_return(packs[source_id], indices[source_id], 4)
        dt = datetime.fromtimestamp(decision_time, tz=timezone.utc)
        values = {
            **returns,
            "eur_cross_confirmation_score": 0.5 * (returns["eurgbp_return_4"] + returns["eurjpy_return_4"]),
            "risk_regime_score": 0.5 * (returns["spx500_return_4"] + returns["nas100_return_4"]),
            "bond_proxy_spread_shock": returns["de10yb_return_4"] - returns["usb10y_return_4"],
            **_session_features(decision_time),
            "utc_hour_sin": math.sin(2.0 * math.pi * (dt.hour + dt.minute / 60.0) / 24.0),
            "utc_hour_cos": math.cos(2.0 * math.pi * (dt.hour + dt.minute / 60.0) / 24.0),
            "weekday_sin": math.sin(2.0 * math.pi * dt.weekday() / 7.0),
            "weekday_cos": math.cos(2.0 * math.pi * dt.weekday() / 7.0),
        }
        vector = [float(values[name]) for name in feature_names]
        if not np.all(np.isfinite(vector)):
            continue
        rows.append(vector)
        times.append(dt.isoformat().replace("+00:00", "Z"))
    return {
        "values": np.asarray(rows, dtype=np.float64),
        "times": np.asarray(times),
        "feature_names": np.asarray(feature_names),
    }


def build_context_feature_matrix(
    connection,
    *,
    contract_path: Path,
    inbox_dir: Path,
    output_dir: Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    coverage = audit_context_coverage(connection, contract_path=contract_path, inbox_dir=inbox_dir)
    if coverage["coverage_status"] != "READY_FOR_OUTCOME_BLIND_CONTEXT_DISCOVERY":
        raise ValueError("context feature matrix is blocked by source coverage")
    source_rows, lineage = _load_context_rows(connection, inbox_dir, contract)
    arrays = build_context_feature_arrays(source_rows, contract)
    contract_hash = payload_hash(contract)
    identity = {
        "builder_version": MATRIX_BUILDER_VERSION,
        "contract_sha256": contract_hash,
        "coverage_audit_id": coverage["audit_id"],
        "source_lineage": lineage,
    }
    artifact_id = f"CONTEXT_MATRIX_{contract['contract_id']}_{payload_hash(identity)[:16]}"
    existing = connection.execute(
        "SELECT payload_json FROM context_feature_artifacts WHERE artifact_id=?", (artifact_id,)
    ).fetchone()
    if existing is not None:
        return json.loads(existing["payload_json"])
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = output_dir / f"{artifact_id}.npz"
    metadata_path = output_dir / f"{artifact_id}.json"
    with tempfile.NamedTemporaryFile(suffix=".npz", dir=output_dir, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        np.savez_compressed(temporary, **arrays)
        temporary.replace(matrix_path)
    finally:
        temporary.unlink(missing_ok=True)
    created = created_at_utc or max(str(row["window_end_utc"]) for row in lineage)
    metadata = {
        "schema": MATRIX_SCHEMA,
        "artifact_id": artifact_id,
        "created_at_utc": created,
        "contract_id": contract["contract_id"],
        "contract_sha256": contract_hash,
        "coverage_audit_id": coverage["audit_id"],
        "builder_version": MATRIX_BUILDER_VERSION,
        "matrix_path": matrix_path.name,
        "matrix_sha256": sha256_file(matrix_path),
        "feature_names": list(arrays["feature_names"]),
        "feature_count": len(arrays["feature_names"]),
        "development_row_count": len(arrays["values"]),
        "earliest_decision_time_utc": str(arrays["times"][0]) if len(arrays["times"]) else None,
        "latest_decision_time_utc": str(arrays["times"][-1]) if len(arrays["times"]) else None,
        "source_lineage": lineage,
        "future_outcomes_included": False,
        "strategy_labels_included": False,
        "validation_rows_included": 0,
        "holdout_rows_included": 0,
        "authority": "LOCKED_RESEARCH_ONLY",
    }
    write_json_atomic(metadata_path, metadata)
    insert_immutable(
        connection, "context_feature_artifacts", "artifact_id", artifact_id, metadata,
        {"created_at_utc": created},
    )
    return metadata


def _nearest_centroid_labels(values: np.ndarray, centroids: np.ndarray, block_size: int = 10000) -> np.ndarray:
    labels = np.empty(len(values), dtype=np.int32)
    centroid_norms = np.sum(centroids * centroids, axis=1)[None, :]
    for start in range(0, len(values), block_size):
        block = values[start : start + block_size]
        distances = np.maximum(
            0.0,
            np.sum(block * block, axis=1)[:, None] + centroid_norms - 2.0 * block @ centroids.T,
        )
        labels[start : start + len(block)] = np.argmin(distances, axis=1)
    return labels


def run_context_discovery(
    connection,
    *,
    contract_path: Path,
    matrix_metadata_path: Path,
    output_path: Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    metadata = json.loads(matrix_metadata_path.read_text(encoding="utf-8"))
    if metadata.get("schema") != MATRIX_SCHEMA or metadata.get("contract_sha256") != payload_hash(contract):
        raise ValueError("context matrix does not match the discovery contract")
    matrix_path = Path(metadata["matrix_path"])
    if not matrix_path.is_absolute():
        matrix_path = matrix_metadata_path.parent / matrix_path
    if sha256_file(matrix_path) != metadata.get("matrix_sha256"):
        raise ValueError("context matrix checksum mismatch")
    with np.load(matrix_path, allow_pickle=False) as archive:
        values = archive["values"]
        times = archive["times"]
        feature_names = [str(value) for value in archive["feature_names"]]
    means = values.mean(axis=0)
    scales = values.std(axis=0)
    scales[scales < 1e-12] = 1.0
    standardized = (values - means) / scales
    settings = contract["clustering"]
    maximum = int(settings["maximum_training_rows"])
    sample_indices = (
        np.linspace(0, len(standardized) - 1, maximum, dtype=int)
        if len(standardized) > maximum else np.arange(len(standardized))
    )
    training = standardized[sample_indices]
    _, centroids, iterations, movement = _kmeans(
        training,
        int(settings["cluster_count"]),
        int(settings["seed"]),
        int(settings["maximum_iterations"]),
        float(settings["tolerance"]),
    )
    all_labels = _nearest_centroid_labels(standardized, centroids)
    cluster_rows: list[dict[str, Any]] = []
    for index, centroid in enumerate(centroids):
        digest = hashlib.sha256(
            (payload_hash(contract) + canonical_json(np.round(centroid, 8).tolist())).encode("utf-8")
        ).hexdigest()[:12]
        top = np.argsort(np.abs(centroid))[::-1][:7]
        cluster_rows.append(
            {
                "machine_cluster_id": f"EURUSD_CONTEXT_V1_{digest}",
                "development_row_count": int(np.sum(all_labels == index)),
                "development_fraction": round(float(np.mean(all_labels == index)), 6),
                "top_standardized_features": [
                    {
                        "feature": feature_names[position],
                        "centroid_z": round(float(centroid[position]), 6),
                        "raw_centroid": round(float(means[position] + centroid[position] * scales[position]), 8),
                    }
                    for position in top
                ],
            }
        )
    cluster_rows.sort(key=lambda row: row["machine_cluster_id"])
    seed = {
        "runner_version": DISCOVERY_RUNNER_VERSION,
        "contract_sha256": payload_hash(contract),
        "matrix_artifact_id": metadata["artifact_id"],
        "matrix_sha256": metadata["matrix_sha256"],
    }
    run_id = "CONTEXT_DISCOVERY_" + hashlib.sha256(canonical_json(seed).encode("utf-8")).hexdigest()[:20]
    existing = connection.execute(
        "SELECT payload_json FROM context_discovery_runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if existing is not None:
        report = json.loads(existing["payload_json"])
        write_json_atomic(output_path, report)
        return report
    created = created_at_utc or str(metadata["created_at_utc"])
    report = {
        "schema": REPORT_SCHEMA,
        "run_id": run_id,
        "created_at_utc": created,
        "status": "DEVELOPMENT_CONTEXT_CLUSTERS_DESCRIBED_OUTCOMES_UNTOUCHED",
        "contract_id": contract["contract_id"],
        "contract_sha256": payload_hash(contract),
        "matrix_artifact_id": metadata["artifact_id"],
        "matrix_sha256": metadata["matrix_sha256"],
        "algorithm": settings["algorithm"],
        "runner_version": DISCOVERY_RUNNER_VERSION,
        "iterations": iterations,
        "converged": movement <= float(settings["tolerance"]),
        "final_max_centroid_movement": movement,
        "development_row_count": len(values),
        "development_distinct_day_count": len({str(value)[:10] for value in times}),
        "training_row_count": len(training),
        "cluster_count": len(cluster_rows),
        "clusters": cluster_rows,
        "validation_rows_inspected": 0,
        "holdout_rows_inspected": 0,
        "future_outcomes_inspected": 0,
        "profitability_claimed": False,
        "direction_or_geometry_assigned": False,
        "comparisons_executed": 0,
        "next_gate": "HUMAN_DESCRIPTIVE_REVIEW_BEFORE_ANY_PREDECLARED_OUTCOME_TEST",
        "authority": "LOCKED_RESEARCH_ONLY",
    }
    write_json_atomic(output_path, report)
    insert_immutable(
        connection, "context_discovery_runs", "run_id", run_id, report,
        {"created_at_utc": created},
    )
    return report


def context_discovery_status(connection) -> dict[str, Any]:
    coverage = connection.execute(
        "SELECT payload_json FROM context_coverage_audits ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    matrix = connection.execute(
        "SELECT payload_json FROM context_feature_artifacts ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    discovery = connection.execute(
        "SELECT payload_json FROM context_discovery_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return {
        "context_discovery_status": (
            "DESCRIBED_RESEARCH_ONLY" if discovery else
            ("MATRIX_READY" if matrix else ("COVERAGE_READY" if coverage else "NOT_STARTED"))
        ),
        "latest_coverage": json.loads(coverage["payload_json"]) if coverage else None,
        "latest_matrix": json.loads(matrix["payload_json"]) if matrix else None,
        "latest_discovery": json.loads(discovery["payload_json"]) if discovery else None,
        "paper_or_live_authority": False,
    }
