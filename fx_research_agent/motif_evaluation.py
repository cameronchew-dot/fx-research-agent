from __future__ import annotations

import gzip
import hashlib
import json
import math
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .motif_discovery import (
    MATRIX_SCHEMA,
    PREDECLARATION_SCHEMA,
    REPORT_SCHEMA,
    _kmeans,
    _series_pack,
    load_contract,
    load_historical_candles,
    parse_utc,
    sha256_file,
    write_json_atomic,
)
from .storage import canonical_json, insert_immutable, payload_hash


PROTOCOL_SCHEMA = "FX_MOTIF_EVALUATION_PROTOCOL_V1"
EVALUATION_SCHEMA = "FX_MOTIF_DEVELOPMENT_EVALUATION_REPORT_V1"
EVENT_SCHEMA = "FX_MOTIF_DEVELOPMENT_EVENT_LEDGER_V1"
EVALUATOR_VERSION = "1.1.0"


def instrument_pip_size(instrument: str) -> float:
    parts = str(instrument).upper().split("_")
    if len(parts) != 2:
        raise ValueError(f"unsupported instrument format for pip sizing: {instrument}")
    return 0.01 if parts[1] == "JPY" else 0.0001


def load_protocol(path: Path, predeclaration_path: Path) -> dict[str, Any]:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("unsupported motif evaluation protocol")
    if protocol.get("predeclaration_file_sha256") != sha256_file(predeclaration_path):
        raise ValueError("evaluation protocol does not match the pinned predeclaration")
    if protocol.get("evaluation_split") != "DEVELOPMENT_ONLY":
        raise ValueError("motif evaluator is development-only")
    test = protocol.get("significance_test") or {}
    if test.get("method") != "ONE_SIDED_PAIRED_SIGN_FLIP_MONTE_CARLO":
        raise ValueError("unsupported motif significance test")
    if int(test.get("draw_count", 0)) <= 0:
        raise ValueError("sign-flip draw count must be positive")
    correction = protocol.get("multiple_comparisons") or {}
    if correction.get("method") != "HOLM_BONFERRONI":
        raise ValueError("motif evaluator requires Holm-Bonferroni")
    authority = protocol.get("authority") or {}
    if authority.get("research_only") is not True or authority.get("paper_or_live_authority") is not False:
        raise ValueError("motif evaluation must remain research-only")
    return protocol


def register_evaluation_protocol(
    connection,
    *,
    protocol_path: Path,
    predeclaration_path: Path,
) -> dict[str, Any]:
    protocol = load_protocol(protocol_path, predeclaration_path)
    predeclaration = json.loads(predeclaration_path.read_text(encoding="utf-8"))
    if predeclaration.get("schema") != PREDECLARATION_SCHEMA:
        raise ValueError("unsupported motif predeclaration")
    if protocol.get("predeclaration_id") != predeclaration.get("predeclaration_id"):
        raise ValueError("evaluation protocol references the wrong predeclaration")
    registered = connection.execute(
        "SELECT payload_hash FROM motif_predeclarations WHERE predeclaration_id = ?",
        (predeclaration["predeclaration_id"],),
    ).fetchone()
    if registered is None or registered["payload_hash"] != payload_hash(predeclaration):
        raise ValueError("exact motif predeclaration must be registered first")
    insert_immutable(
        connection,
        "motif_evaluation_protocols",
        "protocol_id",
        str(protocol["protocol_id"]),
        protocol,
        {"created_at_utc": protocol["created_at_utc"]},
    )
    return {
        "protocol_status": "REGISTERED_DEVELOPMENT_ONLY",
        "protocol_id": protocol["protocol_id"],
        "predeclaration_id": predeclaration["predeclaration_id"],
        "planned_primary_hypothesis_count": predeclaration["planned_confirmation_budget"]["planned_primary_hypothesis_count"],
        "validation_rows_permitted": 0,
        "holdout_rows_permitted": 0,
        "paper_or_live_authority": False,
    }


def _load_matrix(metadata_path: Path) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("schema") != MATRIX_SCHEMA:
        raise ValueError("unsupported motif matrix")
    matrix_path = Path(metadata["matrix_path"])
    if not matrix_path.is_absolute():
        matrix_path = metadata_path.parent / matrix_path
    if sha256_file(matrix_path) != metadata.get("matrix_sha256"):
        raise ValueError("motif matrix checksum mismatch")
    with np.load(matrix_path, allow_pickle=False) as archive:
        arrays = {name: archive[name].copy() for name in archive.files}
    return metadata, arrays


def _cluster_assignments(
    values: np.ndarray,
    splits: np.ndarray,
    feature_names: list[str],
    contract: dict[str, Any],
    discovery: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    development = values[splits == "DEVELOPMENT"]
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
    _, centroids, _, movement = _kmeans(
        training,
        int(settings["cluster_count"]),
        int(settings["seed"]),
        int(settings["maximum_iterations"]),
        float(settings["tolerance"]),
    )
    if movement > float(settings["tolerance"]):
        raise ValueError("reconstructed motif clustering did not converge")
    machine_ids = []
    for centroid in centroids:
        digest = hashlib.sha256(
            (payload_hash(contract) + canonical_json(np.round(centroid, 8).tolist())).encode("utf-8")
        ).hexdigest()[:12]
        machine_ids.append(f"{settings['stable_machine_id_prefix']}_{digest}")
    expected = {row["machine_cluster_id"] for row in discovery.get("clusters") or []}
    if set(machine_ids) != expected:
        raise ValueError("reconstructed motif IDs do not match the pinned discovery run")
    value_norms = np.sum(standardized * standardized, axis=1)[:, None]
    centroid_norms = np.sum(centroids * centroids, axis=1)[None, :]
    distances = np.maximum(0.0, value_norms + centroid_norms - 2.0 * standardized @ centroids.T)
    labels = np.argmin(distances, axis=1)
    return np.asarray([machine_ids[index] for index in labels]), development


def _independent_event_indices(assignments: np.ndarray, motif_id: str, skip_bars: int = 16) -> list[int]:
    events: list[int] = []
    previous_match = False
    last_kept = -skip_bars - 1
    for index, assignment in enumerate(assignments):
        match = str(assignment) == motif_id
        if match and not previous_match and index > last_kept + skip_bars:
            events.append(index)
            last_kept = index
        previous_match = match
    return events


def _raw_index(pack: dict[str, np.ndarray], decision_time: float) -> int:
    index = int(np.searchsorted(pack["end"], decision_time, side="left"))
    if index >= len(pack["end"]) or abs(float(pack["end"][index]) - decision_time) > 1e-6:
        raise ValueError("motif decision time does not map to a completed M15 candle")
    return index


def _trade_outcome(
    pack: dict[str, np.ndarray],
    signal_index: int,
    direction: str,
    horizon: int,
    target_r: float,
    fixed_cost_pips: float,
    pip_size: float,
    development_end: float,
) -> dict[str, Any] | None:
    entry_index = signal_index + 1
    final_index = entry_index + horizon - 1
    if final_index >= len(pack["close"]) or float(pack["end"][final_index]) >= development_end:
        return None
    entry = float(pack["open"][entry_index])
    atr = float(pack["atr14"][signal_index])
    if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
        return None
    sign = 1.0 if direction == "LONG" else -1.0
    if direction == "LONG":
        stop = min(float(pack["low"][signal_index]), entry - 0.75 * atr)
        target = entry + target_r * (entry - stop)
    elif direction == "SHORT":
        stop = max(float(pack["high"][signal_index]), entry + 0.75 * atr)
        target = entry - target_r * (stop - entry)
    else:
        raise ValueError(f"unsupported motif direction: {direction}")
    risk = abs(entry - stop)
    if not np.isfinite(risk) or risk <= 0:
        return None
    gross_r = None
    exit_reason = "HORIZON"
    exit_price = float(pack["close"][final_index])
    maximum_favorable_r = -math.inf
    maximum_adverse_r = math.inf
    for index in range(entry_index, final_index + 1):
        open_ = float(pack["open"][index])
        high = float(pack["high"][index])
        low = float(pack["low"][index])
        favorable = (high - entry) / risk if direction == "LONG" else (entry - low) / risk
        adverse = (low - entry) / risk if direction == "LONG" else (entry - high) / risk
        maximum_favorable_r = max(maximum_favorable_r, favorable)
        maximum_adverse_r = min(maximum_adverse_r, adverse)
        adverse_gap = open_ <= stop if direction == "LONG" else open_ >= stop
        favorable_gap = open_ >= target if direction == "LONG" else open_ <= target
        stop_touched = low <= stop if direction == "LONG" else high >= stop
        target_touched = high >= target if direction == "LONG" else low <= target
        if adverse_gap:
            exit_price = open_
            gross_r = sign * (exit_price - entry) / risk
            exit_reason = "STOP_GAP"
            break
        if favorable_gap:
            exit_price = target
            gross_r = target_r
            exit_reason = "TARGET_GAP_CONSERVATIVE"
            break
        if stop_touched:
            exit_price = stop
            gross_r = -1.0
            exit_reason = "STOP"
            break
        if target_touched:
            exit_price = target
            gross_r = target_r
            exit_reason = "TARGET"
            break
    if gross_r is None:
        gross_r = sign * (exit_price - entry) / risk
    if not np.isfinite(pip_size) or pip_size <= 0:
        raise ValueError("pip size must be positive")
    stop_distance_pips = risk / pip_size
    cost_r = fixed_cost_pips / stop_distance_pips
    return {
        "entry_time_utc": _iso(float(pack["time"][entry_index])),
        "exit_time_utc": _iso(float(pack["end"][min(final_index, index)])),
        "entry": round(entry, 8),
        "stop": round(stop, 8),
        "target": round(target, 8),
        "exit_price": round(exit_price, 8),
        "exit_reason": exit_reason,
        "stop_distance_pips": round(stop_distance_pips, 6),
        "gross_r": round(float(gross_r), 8),
        "cost_r": round(float(cost_r), 8),
        "net_r": round(float(gross_r - cost_r), 8),
        "mfe_r": round(float(maximum_favorable_r), 8),
        "mae_r": round(float(maximum_adverse_r), 8),
    }


def _iso(timestamp: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _metrics(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = np.asarray([float(row[key]) for row in records], dtype=float)
    months: dict[str, list[float]] = defaultdict(list)
    for row, value in zip(records, values):
        months[str(row["decision_time_utc"])[:7]].append(float(value))
    month_means = [float(np.mean(items)) for items in months.values()]
    positives = np.sort(values[values > 0])[::-1]
    top_count = max(1, int(math.ceil(0.05 * len(values)))) if len(values) else 0
    top_fraction = float(positives[:top_count].sum() / positives.sum()) if len(positives) and positives.sum() > 0 else 1.0
    return {
        "event_count": int(len(values)),
        "calendar_month_count": len(months),
        "average_net_r": round(float(np.mean(values)), 8) if len(values) else None,
        "median_net_r": round(float(np.median(values)), 8) if len(values) else None,
        "positive_net_r_rate": round(float(np.mean(values > 0)), 8) if len(values) else None,
        "positive_month_rate": round(float(np.mean(np.asarray(month_means) > 0)), 8) if month_means else None,
        "worst_month_average_net_r": round(float(min(month_means)), 8) if month_means else None,
        "top_five_percent_positive_r_contribution_fraction": round(top_fraction, 8),
        "total_net_r": round(float(values.sum()), 8) if len(values) else 0.0,
    }


def _sign_flip_p_value(differences: np.ndarray, *, draws: int, seed: int) -> float:
    if len(differences) == 0:
        return 1.0
    observed = float(np.mean(differences))
    rng = np.random.default_rng(seed)
    exceedances = 0
    remaining = draws
    while remaining:
        batch = min(1000, remaining)
        signs = rng.integers(0, 2, size=(batch, len(differences)), dtype=np.int8) * 2 - 1
        means = np.mean(signs * differences[None, :], axis=1)
        exceedances += int(np.sum(means >= observed - 1e-15))
        remaining -= batch
    return float((exceedances + 1) / (draws + 1))


def _holm_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (count - rank) * p_values[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def _gate_blocks(summary: dict[str, Any], gates: dict[str, Any], alpha: float) -> list[str]:
    blocks = []
    checks = (
        (summary["event_count"] >= int(gates["minimum_independent_events_per_primary_hypothesis"]), "INSUFFICIENT_INDEPENDENT_EVENTS"),
        (summary["calendar_month_count"] >= int(gates["minimum_calendar_months_with_events"]), "INSUFFICIENT_CALENDAR_MONTHS"),
        (summary["average_net_r"] is not None and summary["average_net_r"] >= float(gates["minimum_average_net_r"]), "AVERAGE_NET_R_BELOW_MIN"),
        (summary["median_net_r"] is not None and summary["median_net_r"] > float(gates["minimum_median_net_r_exclusive"]), "MEDIAN_NET_R_NOT_POSITIVE"),
        (summary["positive_net_r_rate"] is not None and summary["positive_net_r_rate"] >= float(gates["minimum_positive_net_r_rate"]), "POSITIVE_NET_R_RATE_BELOW_MIN"),
        (summary["positive_month_rate"] is not None and summary["positive_month_rate"] >= float(gates["minimum_positive_month_rate"]), "POSITIVE_MONTH_RATE_BELOW_MIN"),
        (summary["worst_month_average_net_r"] is not None and summary["worst_month_average_net_r"] >= float(gates["minimum_worst_month_average_net_r"]), "WORST_MONTH_BELOW_MIN"),
        (summary["top_five_percent_positive_r_contribution_fraction"] <= float(gates["maximum_top_five_percent_positive_r_contribution_fraction"]), "OUTLIER_DEPENDENCE_ABOVE_MAX"),
        (summary["edge_over_opposite_control"] >= float(gates["minimum_average_net_r_edge_over_each_control"]), "OPPOSITE_CONTROL_EDGE_BELOW_MIN"),
        (summary["edge_over_shifted_control"] >= float(gates["minimum_average_net_r_edge_over_each_control"]), "SHIFTED_CONTROL_EDGE_BELOW_MIN"),
        (summary["holm_adjusted_p_value"] <= alpha, "HOLM_SIGNIFICANCE_NOT_CLEAR"),
    )
    for passed, label in checks:
        if not passed:
            blocks.append(label)
    return blocks


def _write_gzip_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as raw:
        temporary = Path(raw.name)
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            compressed.write((canonical_json(payload) + "\n").encode("utf-8"))
    temporary.replace(path)


def evaluate_development(
    connection,
    *,
    contract_path: Path,
    predeclaration_path: Path,
    protocol_path: Path,
    discovery_path: Path,
    matrix_metadata_path: Path,
    inbox_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    predeclaration = json.loads(predeclaration_path.read_text(encoding="utf-8"))
    protocol = load_protocol(protocol_path, predeclaration_path)
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    if discovery.get("schema") != REPORT_SCHEMA:
        raise ValueError("unsupported motif discovery report")
    if sha256_file(discovery_path) != predeclaration.get("source_discovery_report_sha256"):
        raise ValueError("motif discovery report no longer matches the predeclaration")
    for table, id_column, record_id, payload in (
        ("motif_predeclarations", "predeclaration_id", predeclaration["predeclaration_id"], predeclaration),
        ("motif_evaluation_protocols", "protocol_id", protocol["protocol_id"], protocol),
    ):
        row = connection.execute(
            f"SELECT payload_hash FROM {table} WHERE {id_column} = ?", (record_id,)
        ).fetchone()
        if row is None or row["payload_hash"] != payload_hash(payload):
            raise ValueError(f"exact registered record required before evaluation: {table}:{record_id}")
    metadata, arrays = _load_matrix(matrix_metadata_path)
    if metadata.get("artifact_id") != predeclaration.get("source_matrix_artifact_id"):
        raise ValueError("matrix does not match the predeclaration")
    assignments, _ = _cluster_assignments(
        arrays["values"], arrays["splits"], [str(value) for value in arrays["feature_names"]], contract, discovery
    )
    development_mask = arrays["splits"] == "DEVELOPMENT"
    development_times = arrays["times"][development_mask]
    candles, _ = load_historical_candles(connection, inbox_dir, contract)
    pack = _series_pack(candles["M15"])
    development_end = parse_utc(contract["development"]["end_utc_exclusive"])
    target_r = float(predeclaration["execution_geometry"]["target_r"])
    cost = float(predeclaration["cost_model"]["fixed_round_trip_cost_pips"])
    pip_size = instrument_pip_size(str(contract["instrument"]))
    horizons = [int(value) for value in predeclaration["execution_geometry"]["horizon_bars"]]
    all_event_rows: list[dict[str, Any]] = []
    hypothesis_rows: list[dict[str, Any]] = []
    raw_p_values: list[float] = []
    min_events = int(predeclaration["objective_gates"]["minimum_independent_events_per_primary_hypothesis"])
    test = protocol["significance_test"]
    for motif_offset, motif in enumerate(predeclaration["selected_motifs"]):
        event_indices = _independent_event_indices(assignments, motif["machine_cluster_id"])
        for horizon in horizons:
            records = []
            for event_index in event_indices:
                shifted_index = event_index + 480
                if shifted_index >= len(development_times):
                    continue
                decision_time = parse_utc(development_times[event_index])
                shifted_time = parse_utc(development_times[shifted_index])
                signal_index = _raw_index(pack, decision_time)
                shifted_signal_index = _raw_index(pack, shifted_time)
                primary = _trade_outcome(
                    pack, signal_index, motif["direction"], horizon, target_r, cost, pip_size, development_end
                )
                opposite_direction = "SHORT" if motif["direction"] == "LONG" else "LONG"
                opposite = _trade_outcome(
                    pack, signal_index, opposite_direction, horizon, target_r, cost, pip_size, development_end
                )
                shifted = _trade_outcome(
                    pack, shifted_signal_index, motif["direction"], horizon, target_r, cost, pip_size, development_end
                )
                if primary is None or opposite is None or shifted is None:
                    continue
                record = {
                    "motif_id": motif["machine_cluster_id"],
                    "mechanism_label": motif["mechanism_label"],
                    "direction": motif["direction"],
                    "horizon_bars": horizon,
                    "decision_time_utc": str(development_times[event_index]),
                    "shifted_control_decision_time_utc": str(development_times[shifted_index]),
                    "primary": primary,
                    "opposite_direction_control": opposite,
                    "shifted_event_control": shifted,
                }
                records.append(record)
                all_event_rows.append(record)
            metric_rows = [
                {
                    "decision_time_utc": row["decision_time_utc"],
                    "primary_net_r": row["primary"]["net_r"],
                    "opposite_net_r": row["opposite_direction_control"]["net_r"],
                    "shifted_net_r": row["shifted_event_control"]["net_r"],
                }
                for row in records
            ]
            primary_metrics = _metrics(metric_rows, "primary_net_r")
            opposite_metrics = _metrics(metric_rows, "opposite_net_r")
            shifted_metrics = _metrics(metric_rows, "shifted_net_r")
            primary_values = np.asarray([row["primary_net_r"] for row in metric_rows], dtype=float)
            opposite_values = np.asarray([row["opposite_net_r"] for row in metric_rows], dtype=float)
            shifted_values = np.asarray([row["shifted_net_r"] for row in metric_rows], dtype=float)
            primary_metrics["edge_over_opposite_control"] = round(
                float(primary_metrics["average_net_r"] - opposite_metrics["average_net_r"]), 8
            ) if records else 0.0
            primary_metrics["edge_over_shifted_control"] = round(
                float(primary_metrics["average_net_r"] - shifted_metrics["average_net_r"]), 8
            ) if records else 0.0
            differences = primary_values - np.maximum(opposite_values, shifted_values)
            p_value = 1.0
            if len(records) >= min_events:
                p_value = _sign_flip_p_value(
                    differences,
                    draws=int(test["draw_count"]),
                    seed=int(test["seed"]) + motif_offset * 100 + horizon,
                )
            raw_p_values.append(p_value)
            hypothesis_rows.append(
                {
                    "hypothesis_id": f"{motif['machine_cluster_id']}_{motif['direction']}_H{horizon}",
                    "motif_id": motif["machine_cluster_id"],
                    "mechanism_label": motif["mechanism_label"],
                    "direction": motif["direction"],
                    "horizon_bars": horizon,
                    "primary": primary_metrics,
                    "opposite_direction_control": opposite_metrics,
                    "shifted_event_control": shifted_metrics,
                    "paired_edge_over_stronger_control_average_r": round(float(np.mean(differences)), 8) if len(differences) else None,
                    "raw_sign_flip_p_value": round(float(p_value), 10),
                }
            )
    adjusted = _holm_adjust(raw_p_values)
    alpha = float(protocol["multiple_comparisons"]["familywise_alpha"])
    survivor_count = 0
    for row, adjusted_p in zip(hypothesis_rows, adjusted):
        row["primary"]["holm_adjusted_p_value"] = round(float(adjusted_p), 10)
        blocks = _gate_blocks(row["primary"], predeclaration["objective_gates"], alpha)
        row["gate_blocks"] = blocks
        row["development_survivor"] = not blocks
        survivor_count += int(not blocks)
    event_payload = {
        "schema": EVENT_SCHEMA,
        "protocol_id": protocol["protocol_id"],
        "predeclaration_id": predeclaration["predeclaration_id"],
        "matrix_artifact_id": metadata["artifact_id"],
        "split": "DEVELOPMENT_ONLY",
        "events": all_event_rows,
    }
    run_seed = {
        "evaluator_version": EVALUATOR_VERSION,
        "protocol_sha256": payload_hash(protocol),
        "predeclaration_sha256": payload_hash(predeclaration),
        "matrix_sha256": metadata["matrix_sha256"],
    }
    run_id = f"MOTIF_DEVELOPMENT_EVALUATION_{hashlib.sha256(canonical_json(run_seed).encode()).hexdigest()[:20]}"
    output_dir.mkdir(parents=True, exist_ok=True)
    event_path = output_dir / f"{run_id}.events.json.gz"
    _write_gzip_json(event_path, event_payload)
    report = {
        "schema": EVALUATION_SCHEMA,
        "evaluation_run_id": run_id,
        "created_at_utc": protocol["created_at_utc"],
        "status": (
            "DEVELOPMENT_SURVIVORS_REQUIRE_SEALED_VALIDATION_APPROVAL"
            if survivor_count else "NO_DEVELOPMENT_SURVIVORS"
        ),
        "evaluator_version": EVALUATOR_VERSION,
        "protocol_id": protocol["protocol_id"],
        "predeclaration_id": predeclaration["predeclaration_id"],
        "matrix_artifact_id": metadata["artifact_id"],
        "hypothesis_count": len(hypothesis_rows),
        "development_survivor_count": survivor_count,
        "hypotheses": hypothesis_rows,
        "event_ledger_path": event_path.name,
        "event_ledger_sha256": sha256_file(event_path),
        "event_ledger_row_count": len(all_event_rows),
        "validation_rows_inspected": 0,
        "holdout_rows_inspected": 0,
        "automatic_validation_access_granted": False,
        "automatic_campaign_creation": False,
        "paper_or_live_authority": False,
        "next_gate": (
            "HUMAN_REVIEW_BEFORE_ANY_SEALED_VALIDATION_ACCESS"
            if survivor_count else "ARCHIVE_RESULT_WITHOUT_RETUNING"
        ),
    }
    report_path = output_dir / f"{run_id}.json"
    write_json_atomic(report_path, report)
    write_json_atomic(output_dir / "latest_development_evaluation.json", report)
    insert_immutable(
        connection,
        "motif_evaluation_runs",
        "evaluation_run_id",
        run_id,
        report,
        {"created_at_utc": protocol["created_at_utc"]},
    )
    return report
