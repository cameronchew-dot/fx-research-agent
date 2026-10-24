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
from .storage import canonical_json, insert_immutable, payload_hash


CONTRACT_SCHEMA = "FX_MOTIF_DISCOVERY_CONTRACT_V1"
MATRIX_SCHEMA = "FX_MOTIF_FEATURE_MATRIX_V1"
REPORT_SCHEMA = "FX_MOTIF_DISCOVERY_REPORT_V1"
MATRIX_BUILDER_VERSION = "1.0.2"
DISCOVERY_RUNNER_VERSION = "1.0.1"
FORBIDDEN_FEATURE_TOKENS = (
    "outcome", "forward", "target", "terminal", "mfe", "mae", "pnl", "net_r",
    "strategy", "family", "candidate", "signal", "label",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: Any) -> float:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("unsupported motif discovery contract")
    features = payload.get("feature_names")
    if not isinstance(features, list) or not features or len(features) != len(set(features)):
        raise ValueError("motif feature names must be a unique non-empty list")
    offending = [name for name in features if any(token in str(name).lower() for token in FORBIDDEN_FEATURE_TOKENS)]
    if offending:
        raise ValueError(f"future/strategy-derived motif features are forbidden: {offending}")
    if payload.get("strategy_labels_allowed") is not False or payload.get("future_outcomes_allowed_in_features") is not False:
        raise ValueError("motif discovery must exclude strategy labels and future outcomes")
    if not (payload.get("authority") or {}).get("research_only"):
        raise ValueError("motif discovery contract must remain research-only")
    return payload


def _load_payload(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def load_historical_candles(
    connection,
    inbox_dir: Path,
    contract: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    instrument = str(contract["instrument"])
    required = {str(value) for value in contract["required_granularities"]}
    candles: dict[tuple[str, str], dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    rows = connection.execute(
        "SELECT manifest_id, payload_json, usable_for_testing FROM market_data_manifests ORDER BY registered_at_utc"
    ).fetchall()
    for row in rows:
        manifest = json.loads(row["payload_json"])
        if not int(row["usable_for_testing"]):
            continue
        if manifest.get("instrument") != instrument:
            continue
        if contract["source_data_class"] not in set(manifest.get("data_classes") or []):
            continue
        manifest_path = inbox_dir / f"{manifest['manifest_id']}.manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"registered motif source manifest missing from inbox: {manifest['manifest_id']}")
        validated = validate_manifest(manifest_path)
        payload_path = inbox_dir / str(validated["payload_path"])
        payload = _load_payload(payload_path)
        if payload.get("schema") != "FX_HISTORICAL_MARKET_DATA_PAYLOAD_V1":
            raise ValueError("motif discovery requires a sealed historical candle payload")
        quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
        if quality.get("future_outcomes_exported") is not False or quality.get("strategy_labels_exported") is not False:
            raise ValueError("historical motif source does not prove outcome/label exclusion")
        for candle in payload.get("completed_candles") or []:
            if candle.get("instrument") != instrument or candle.get("granularity") not in required:
                continue
            key = (str(candle["granularity"]), str(candle["candle_time_utc"]))
            existing = candles.get(key)
            if existing is not None and canonical_json(existing) != canonical_json(candle):
                raise ValueError(f"conflicting historical candle rewrite: {key}")
            candles[key] = candle
        sources.append(
            {
                "manifest_id": manifest["manifest_id"],
                "payload_sha256": manifest["payload_sha256"],
                "window_start_utc": manifest["window_start_utc"],
                "window_end_utc": manifest["window_end_utc"],
                "created_at_utc": manifest["created_at_utc"],
            }
        )
    grouped = {
        granularity: sorted(
            [row for (tf, _), row in candles.items() if tf == granularity],
            key=lambda item: item["candle_time_utc"],
        )
        for granularity in required
    }
    missing = sorted(granularity for granularity, items in grouped.items() if not items)
    if missing:
        raise ValueError(f"missing historical motif granularities: {missing}")
    return grouped, sources


def _numeric(rows: list[dict[str, Any]], key: str) -> np.ndarray:
    return np.asarray([float(row[key]) if row.get(key) is not None else np.nan for row in rows], dtype=float)


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    alpha = 2.0 / (span + 1.0)
    state = np.nan
    for index, value in enumerate(values):
        if not np.isfinite(value):
            continue
        state = value if not np.isfinite(state) else alpha * value + (1.0 - alpha) * state
        output[index] = state
    return output


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    valid = np.isfinite(values)
    sums = np.cumsum(np.where(valid, values, 0.0))
    counts = np.cumsum(valid.astype(int))
    for index in range(window - 1, len(values)):
        left = index - window
        total = sums[index] - (sums[left] if left >= 0 else 0.0)
        count = counts[index] - (counts[left] if left >= 0 else 0)
        if count == window:
            output[index] = total / window
    return output


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    mean = _rolling_mean(values, window)
    mean_sq = _rolling_mean(values * values, window)
    return np.sqrt(np.maximum(0.0, mean_sq - mean * mean))


def _series_pack(rows: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    close = _numeric(rows, "close")
    high = _numeric(rows, "high")
    low = _numeric(rows, "low")
    open_ = _numeric(rows, "open")
    volume = _numeric(rows, "volume")
    previous = np.roll(close, 1)
    previous[0] = np.nan
    true_range = np.nanmax(np.vstack((high - low, np.abs(high - previous), np.abs(low - previous))), axis=0)
    returns = np.full(len(close), np.nan)
    returns[1:] = np.log(close[1:] / close[:-1])
    return {
        "time": np.asarray([parse_utc(row["candle_time_utc"]) for row in rows]),
        "end": np.asarray([parse_utc(row.get("candle_end_time_utc") or row["candle_time_utc"]) for row in rows]),
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
        "atr14": _rolling_mean(true_range, 14), "atr96": _rolling_mean(true_range, 96),
        "ema20": _ema(close, 20), "ema50": _ema(close, 50), "ema200": _ema(close, 200),
        "return": returns, "vol16": _rolling_std(returns, 16), "vol96": _rolling_std(returns, 96),
        "volume_mean96": _rolling_mean(volume, 96), "volume_std96": _rolling_std(volume, 96),
    }


def _asof(pack: dict[str, np.ndarray], decision_time: float) -> int:
    return int(np.searchsorted(pack["end"], decision_time, side="right")) - 1


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if np.isfinite(numerator) and np.isfinite(denominator) and abs(denominator) > 1e-12 else np.nan


def build_feature_arrays(
    candles: dict[str, list[dict[str, Any]]],
    contract: dict[str, Any],
) -> dict[str, np.ndarray]:
    packs = {granularity: _series_pack(rows) for granularity, rows in candles.items()}
    base = packs[str(contract["base_granularity"])]
    feature_names = list(contract["feature_names"])
    rows: list[list[float]] = []
    times: list[str] = []
    splits: list[str] = []
    dev = contract["development"]
    validation = contract["validation"]
    holdout = contract["holdout"]
    dev_start, dev_end = parse_utc(dev["start_utc"]), parse_utc(dev["end_utc_exclusive"])
    val_start, val_end = parse_utc(validation["start_utc"]), parse_utc(validation["end_utc_exclusive"])
    holdout_start = parse_utc(holdout["start_utc"])

    for index in range(200, len(base["close"])):
        decision_time = float(base["end"][index])
        atr14 = float(base["atr14"][index])
        candle_range = float(base["high"][index] - base["low"][index])
        dt = datetime.fromtimestamp(decision_time, tz=timezone.utc)
        h1_index = _asof(packs["H1"], decision_time)
        h4_index = _asof(packs["H4"], decision_time)
        day_index = _asof(packs["D"], decision_time)
        if min(h1_index, h4_index, day_index) < 20:
            continue
        h1, h4, daily = packs["H1"], packs["H4"], packs["D"]
        values = {
            "return_1": float(base["return"][index]),
            "return_4": math.log(float(base["close"][index]) / float(base["close"][index - 4])),
            "return_16": math.log(float(base["close"][index]) / float(base["close"][index - 16])),
            "range_atr14": _ratio(candle_range, atr14),
            "body_ratio": _ratio(abs(float(base["close"][index] - base["open"][index])), candle_range),
            "upper_wick_ratio": _ratio(float(base["high"][index] - max(base["open"][index], base["close"][index])), candle_range),
            "lower_wick_ratio": _ratio(float(min(base["open"][index], base["close"][index]) - base["low"][index]), candle_range),
            "atr14_atr96_ratio": _ratio(atr14, float(base["atr96"][index])),
            "realized_vol16_vol96_ratio": _ratio(float(base["vol16"][index]), float(base["vol96"][index])),
            "ema20_distance_atr": _ratio(float(base["close"][index] - base["ema20"][index]), atr14),
            "ema50_distance_atr": _ratio(float(base["close"][index] - base["ema50"][index]), atr14),
            "ema200_distance_atr": _ratio(float(base["close"][index] - base["ema200"][index]), atr14),
            "volume_z96": _ratio(float(base["volume"][index] - base["volume_mean96"][index]), float(base["volume_std96"][index])),
            "prior_day_high_distance_atr": _ratio(float(base["close"][index] - daily["high"][day_index]), atr14),
            "prior_day_low_distance_atr": _ratio(float(base["close"][index] - daily["low"][day_index]), atr14),
            "h1_return_1": float(h1["return"][h1_index]),
            "h1_ema20_distance_atr": _ratio(float(h1["close"][h1_index] - h1["ema20"][h1_index]), float(h1["atr14"][h1_index])),
            "h4_return_1": float(h4["return"][h4_index]),
            "h4_ema20_distance_atr": _ratio(float(h4["close"][h4_index] - h4["ema20"][h4_index]), float(h4["atr14"][h4_index])),
            "daily_return_1": float(daily["return"][day_index]),
            "daily_ema20_distance_atr": _ratio(float(daily["close"][day_index] - daily["ema20"][day_index]), float(daily["atr14"][day_index])),
            "utc_hour_sin": math.sin(2.0 * math.pi * (dt.hour + dt.minute / 60.0) / 24.0),
            "utc_hour_cos": math.cos(2.0 * math.pi * (dt.hour + dt.minute / 60.0) / 24.0),
            "weekday_sin": math.sin(2.0 * math.pi * dt.weekday() / 7.0),
            "weekday_cos": math.cos(2.0 * math.pi * dt.weekday() / 7.0),
        }
        vector = [float(values[name]) for name in feature_names]
        if not np.all(np.isfinite(vector)):
            continue
        if dev_start <= decision_time < dev_end:
            split = "DEVELOPMENT"
        elif val_start <= decision_time < val_end:
            split = "VALIDATION_SEALED"
        elif decision_time >= holdout_start:
            split = "HOLDOUT_SEALED"
        else:
            split = "OUTSIDE_DECLARED_WINDOWS"
        rows.append(vector)
        times.append(dt.isoformat().replace("+00:00", "Z"))
        splits.append(split)
    return {
        "values": np.asarray(rows, dtype=np.float64),
        "times": np.asarray(times),
        "splits": np.asarray(splits),
        "feature_names": np.asarray(feature_names),
    }


def build_feature_matrix(
    connection,
    *,
    contract_path: Path,
    inbox_dir: Path,
    output_dir: Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    candles, sources = load_historical_candles(connection, inbox_dir, contract)
    arrays = build_feature_arrays(candles, contract)
    contract_hash = payload_hash(contract)
    source_hash = payload_hash(
        {
            "builder_version": MATRIX_BUILDER_VERSION,
            "contract_sha256": contract_hash,
            "sources": sources,
        }
    )
    artifact_id = f"MOTIF_MATRIX_{contract['contract_id']}_{source_hash[:16]}"
    matrix_path = output_dir / f"{artifact_id}.npz"
    metadata_path = output_dir / f"{artifact_id}.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".npz", dir=output_dir, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        np.savez_compressed(temporary, **arrays)
        temporary.replace(matrix_path)
    finally:
        temporary.unlink(missing_ok=True)
    counts = {name: int(np.sum(arrays["splits"] == name)) for name in np.unique(arrays["splits"])}
    created = created_at_utc or max(str(source["created_at_utc"]) for source in sources)
    metadata = {
        "schema": MATRIX_SCHEMA,
        "artifact_id": artifact_id,
        "created_at_utc": created,
        "contract_id": contract["contract_id"],
        "contract_sha256": contract_hash,
        "builder_version": MATRIX_BUILDER_VERSION,
        "matrix_path": matrix_path.name,
        "matrix_sha256": sha256_file(matrix_path),
        "feature_names": list(arrays["feature_names"]),
        "feature_count": len(arrays["feature_names"]),
        "row_count": len(arrays["values"]),
        "split_counts": counts,
        "earliest_decision_time_utc": str(arrays["times"][0]) if len(arrays["times"]) else None,
        "latest_decision_time_utc": str(arrays["times"][-1]) if len(arrays["times"]) else None,
        "source_manifests": sources,
        "future_outcomes_included": False,
        "strategy_labels_included": False,
        "authority": "LOCKED_RESEARCH_ONLY",
    }
    write_json_atomic(metadata_path, metadata)
    insert_immutable(connection, "motif_feature_artifacts", "artifact_id", artifact_id, metadata, {"created_at_utc": created})
    return metadata


def _kmeans(values: np.ndarray, cluster_count: int, seed: int, iterations: int, tolerance: float) -> tuple[np.ndarray, np.ndarray, int, float]:
    rng = np.random.default_rng(seed)
    centroids = np.empty((cluster_count, values.shape[1]), dtype=float)
    centroids[0] = values[int(rng.integers(0, len(values)))]
    distance = np.sum((values - centroids[0]) ** 2, axis=1)
    for index in range(1, cluster_count):
        total = float(distance.sum())
        choice = int(rng.integers(0, len(values))) if total <= 0 else int(rng.choice(len(values), p=distance / total))
        centroids[index] = values[choice]
        distance = np.minimum(distance, np.sum((values - centroids[index]) ** 2, axis=1))
    labels = np.zeros(len(values), dtype=int)
    completed = 0
    movement = math.inf
    value_norms = np.sum(values * values, axis=1)[:, None]
    for completed in range(1, iterations + 1):
        centroid_norms = np.sum(centroids * centroids, axis=1)[None, :]
        distances = np.maximum(0.0, value_norms + centroid_norms - 2.0 * values @ centroids.T)
        labels = np.argmin(distances, axis=1)
        next_centroids = centroids.copy()
        for cluster in range(cluster_count):
            members = values[labels == cluster]
            if len(members):
                next_centroids[cluster] = members.mean(axis=0)
        movement = float(np.max(np.linalg.norm(next_centroids - centroids, axis=1)))
        centroids = next_centroids
        if movement <= tolerance:
            break
    return labels, centroids, completed, movement


def run_discovery(
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
        raise ValueError("motif matrix does not match the discovery contract")
    matrix_path = Path(metadata["matrix_path"])
    if not matrix_path.is_absolute():
        matrix_path = matrix_metadata_path.parent / matrix_path
    if sha256_file(matrix_path) != metadata.get("matrix_sha256"):
        raise ValueError("motif matrix checksum mismatch")
    with np.load(matrix_path, allow_pickle=False) as archive:
        values = archive["values"]
        times = archive["times"]
        splits = archive["splits"]
        feature_names = [str(value) for value in archive["feature_names"]]
    development_mask = splits == "DEVELOPMENT"
    development = values[development_mask]
    development_times = times[development_mask]
    distinct_days = len({str(value)[:10] for value in development_times})
    required = contract["development"]
    if len(development) < int(required["minimum_rows"]) or distinct_days < int(required["minimum_distinct_days"]):
        raise ValueError(
            f"insufficient development coverage: rows={len(development)} days={distinct_days} "
            f"required_rows={required['minimum_rows']} required_days={required['minimum_distinct_days']}"
        )
    means = development.mean(axis=0)
    scales = development.std(axis=0)
    scales[scales < 1e-12] = 1.0
    standardized = (development - means) / scales
    settings = contract["clustering"]
    maximum = int(settings["maximum_training_rows"])
    if len(standardized) > maximum:
        sample_indices = np.linspace(0, len(standardized) - 1, maximum, dtype=int)
        training = standardized[sample_indices]
    else:
        training = standardized
    labels, centroids, iterations, final_movement = _kmeans(
        training,
        int(settings["cluster_count"]),
        int(settings["seed"]),
        int(settings["maximum_iterations"]),
        float(settings["tolerance"]),
    )
    cluster_rows = []
    for index, centroid in enumerate(centroids):
        digest = hashlib.sha256(
            (payload_hash(contract) + canonical_json(np.round(centroid, 8).tolist())).encode("utf-8")
        ).hexdigest()[:12]
        top = np.argsort(np.abs(centroid))[::-1][:5]
        cluster_rows.append(
            {
                "machine_cluster_id": f"{settings['stable_machine_id_prefix']}_{digest}",
                "training_row_count": int(np.sum(labels == index)),
                "top_standardized_features": [
                    {"feature": feature_names[position], "centroid_z": round(float(centroid[position]), 6)}
                    for position in top
                ],
            }
        )
    cluster_rows.sort(key=lambda row: row["machine_cluster_id"])
    budget = contract["planned_confirmation_budget"]
    planned = (
        len(cluster_rows)
        * len(budget["directions"])
        * len(budget["horizon_bars"])
        * int(budget["geometry_count_per_cluster_direction_horizon"])
    )
    alpha = float(budget["familywise_alpha"])
    created = created_at_utc or str(metadata["created_at_utc"])
    run_seed = {
        "runner_version": DISCOVERY_RUNNER_VERSION,
        "contract_sha256": payload_hash(contract),
        "matrix_artifact_id": metadata["artifact_id"],
        "matrix_sha256": metadata["matrix_sha256"],
        "algorithm": settings["algorithm"],
        "seed": settings["seed"],
    }
    run_id = f"MOTIF_DISCOVERY_{hashlib.sha256(canonical_json(run_seed).encode('utf-8')).hexdigest()[:20]}"
    report = {
        "schema": REPORT_SCHEMA,
        "run_id": run_id,
        "created_at_utc": created,
        "status": "DEVELOPMENT_CLUSTERS_DESCRIBED_HOLDOUT_UNTOUCHED",
        "contract_id": contract["contract_id"],
        "contract_sha256": payload_hash(contract),
        "matrix_artifact_id": metadata["artifact_id"],
        "matrix_sha256": metadata["matrix_sha256"],
        "algorithm": settings["algorithm"],
        "runner_version": DISCOVERY_RUNNER_VERSION,
        "iterations": iterations,
        "converged": final_movement <= float(settings["tolerance"]),
        "final_max_centroid_movement": final_movement,
        "development_row_count": len(development),
        "development_distinct_day_count": distinct_days,
        "training_row_count": len(training),
        "cluster_count": len(cluster_rows),
        "clusters": cluster_rows,
        "validation_rows_inspected": 0,
        "holdout_rows_inspected": 0,
        "future_outcomes_inspected": 0,
        "profitability_claimed": False,
        "fdr_ledger": {
            "planned_hypothesis_count": planned,
            "familywise_alpha": alpha,
            "bonferroni_reference_alpha": alpha / planned,
            "required_correction": budget["correction"],
            "comparisons_executed": 0,
        },
        "next_gate": "HUMAN_REVIEW_AND_PREDECLARATION_BEFORE_ANY_OUTCOME_EVALUATION",
        "authority": "LOCKED_RESEARCH_ONLY",
    }
    write_json_atomic(output_path, report)
    insert_immutable(connection, "motif_discovery_runs", "run_id", run_id, report, {"created_at_utc": created})
    return report


def motif_status(connection) -> dict[str, Any]:
    matrix = connection.execute(
        "SELECT payload_json FROM motif_feature_artifacts ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    run = connection.execute(
        "SELECT payload_json FROM motif_discovery_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return {
        "motif_discovery_status": "DESCRIBED_RESEARCH_ONLY" if run else ("MATRIX_READY" if matrix else "NOT_STARTED"),
        "latest_matrix": json.loads(matrix["payload_json"]) if matrix else None,
        "latest_run": json.loads(run["payload_json"]) if run else None,
        "paper_or_live_authority": False,
    }
