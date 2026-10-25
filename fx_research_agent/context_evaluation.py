from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .context_discovery import (
    MATRIX_SCHEMA,
    REPORT_SCHEMA,
    _load_context_rows,
    _nearest_centroid_labels,
    load_contract,
)
from .motif_discovery import _kmeans, _series_pack, parse_utc, sha256_file, write_json_atomic
from .motif_evaluation import (
    _gate_blocks,
    _holm_adjust,
    _independent_event_indices,
    _metrics,
    _raw_index,
    _sign_flip_p_value,
    _write_gzip_json,
)
from .storage import canonical_json, insert_immutable, payload_hash


PREDECLARATION_SCHEMA = "FX_CONTEXT_PREDECLARATION_V1"
PROTOCOL_SCHEMA = "FX_CONTEXT_EVALUATION_PROTOCOL_V1"
EVALUATION_SCHEMA = "FX_CONTEXT_DEVELOPMENT_EVALUATION_REPORT_V1"
EVENT_SCHEMA = "FX_CONTEXT_DEVELOPMENT_EVENT_LEDGER_V1"
EVALUATOR_VERSION = "1.0.0"
PIP_SIZE = 0.0001


def load_protocol(path: Path, predeclaration_path: Path) -> dict[str, Any]:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("unsupported context evaluation protocol")
    if protocol.get("predeclaration_file_sha256") != sha256_file(predeclaration_path):
        raise ValueError("context evaluation protocol does not match the pinned predeclaration")
    if protocol.get("evaluation_split") != "DEVELOPMENT_ONLY":
        raise ValueError("context evaluator is development-only")
    test = protocol.get("significance_test") or {}
    if test.get("method") != "ONE_SIDED_PAIRED_SIGN_FLIP_MONTE_CARLO":
        raise ValueError("unsupported context significance test")
    if int(test.get("draw_count", 0)) <= 0:
        raise ValueError("sign-flip draw count must be positive")
    if (protocol.get("multiple_comparisons") or {}).get("method") != "HOLM_BONFERRONI":
        raise ValueError("context evaluator requires Holm-Bonferroni")
    authority = protocol.get("authority") or {}
    if authority.get("research_only") is not True or authority.get("paper_or_live_authority") is not False:
        raise ValueError("context evaluation must remain research-only")
    return protocol


def register_predeclaration(
    connection,
    *,
    selection_path: Path,
    discovery_path: Path,
) -> dict[str, Any]:
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    if selection.get("schema") != PREDECLARATION_SCHEMA:
        raise ValueError("unsupported context predeclaration schema")
    if discovery.get("schema") != REPORT_SCHEMA:
        raise ValueError("unsupported context discovery report")
    if selection.get("source_discovery_run_id") != discovery.get("run_id"):
        raise ValueError("context predeclaration does not match the pinned discovery run")
    if selection.get("source_matrix_artifact_id") != discovery.get("matrix_artifact_id"):
        raise ValueError("context predeclaration does not match the pinned feature matrix")
    if selection.get("source_discovery_report_sha256") != sha256_file(discovery_path):
        raise ValueError("context predeclaration does not match the discovery checksum")
    if discovery.get("future_outcomes_inspected") != 0 or discovery.get("profitability_claimed") is not False:
        raise ValueError("context predeclaration requires an outcome-blind discovery report")
    available = {row["machine_cluster_id"] for row in discovery.get("clusters") or []}
    contexts = selection.get("selected_contexts")
    if not isinstance(contexts, list) or not contexts:
        raise ValueError("context predeclaration requires selected contexts")
    selected = [str(row.get("machine_cluster_id")) for row in contexts]
    if len(selected) != len(set(selected)) or not set(selected).issubset(available):
        raise ValueError("context predeclaration contains duplicate or unknown cluster IDs")
    if any(row.get("direction") not in {"LONG", "SHORT"} for row in contexts):
        raise ValueError("context predeclaration directions must be LONG or SHORT")
    planned = selection.get("planned_confirmation_budget") or {}
    horizons = planned.get("horizon_bars") or []
    expected = len(contexts) * len(horizons)
    if planned.get("selected_context_count") != len(contexts):
        raise ValueError("context selected count does not match")
    if (selection.get("execution_geometry") or {}).get("horizon_bars") != horizons:
        raise ValueError("context execution and hypothesis-budget horizons do not match")
    if planned.get("planned_primary_hypothesis_count") != expected:
        raise ValueError("context hypothesis budget does not match contexts x horizons")
    if planned.get("correction") != "HOLM_BONFERRONI_REQUIRED":
        raise ValueError("context predeclaration must retain Holm-Bonferroni correction")
    authority = selection.get("authority") or {}
    if authority.get("research_only") is not True or authority.get("paper_or_live_authority") is not False:
        raise ValueError("context predeclaration must remain research-only")
    record_id = str(selection["predeclaration_id"])
    insert_immutable(
        connection,
        "context_predeclarations",
        "predeclaration_id",
        record_id,
        selection,
        {"created_at_utc": selection["predeclared_at_utc"]},
    )
    return {
        "predeclaration_status": "REGISTERED_RESEARCH_ONLY",
        "predeclaration_id": record_id,
        "selected_context_count": len(contexts),
        "planned_primary_hypothesis_count": expected,
        "validation_rows_inspected": 0,
        "holdout_rows_inspected": 0,
        "future_outcomes_inspected": 0,
        "paper_or_live_authority": False,
    }


def register_evaluation_protocol(
    connection,
    *,
    protocol_path: Path,
    predeclaration_path: Path,
) -> dict[str, Any]:
    protocol = load_protocol(protocol_path, predeclaration_path)
    predeclaration = json.loads(predeclaration_path.read_text(encoding="utf-8"))
    if predeclaration.get("schema") != PREDECLARATION_SCHEMA:
        raise ValueError("unsupported context predeclaration")
    if protocol.get("predeclaration_id") != predeclaration.get("predeclaration_id"):
        raise ValueError("context protocol references the wrong predeclaration")
    registered = connection.execute(
        "SELECT payload_hash FROM context_predeclarations WHERE predeclaration_id=?",
        (predeclaration["predeclaration_id"],),
    ).fetchone()
    if registered is None or registered["payload_hash"] != payload_hash(predeclaration):
        raise ValueError("exact context predeclaration must be registered first")
    insert_immutable(
        connection,
        "context_evaluation_protocols",
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
        raise ValueError("unsupported context matrix")
    matrix_path = Path(metadata["matrix_path"])
    if not matrix_path.is_absolute():
        matrix_path = metadata_path.parent / matrix_path
    if sha256_file(matrix_path) != metadata.get("matrix_sha256"):
        raise ValueError("context matrix checksum mismatch")
    with np.load(matrix_path, allow_pickle=False) as archive:
        arrays = {name: archive[name].copy() for name in archive.files}
    return metadata, arrays


def _cluster_assignments(
    values: np.ndarray,
    contract: dict[str, Any],
    discovery: dict[str, Any],
) -> np.ndarray:
    means = values.mean(axis=0)
    scales = values.std(axis=0)
    scales[scales < 1e-12] = 1.0
    standardized = (values - means) / scales
    settings = contract["clustering"]
    maximum = int(settings["maximum_training_rows"])
    training = standardized[
        np.linspace(0, len(standardized) - 1, maximum, dtype=int)
    ] if len(standardized) > maximum else standardized
    _, centroids, _, movement = _kmeans(
        training,
        int(settings["cluster_count"]),
        int(settings["seed"]),
        int(settings["maximum_iterations"]),
        float(settings["tolerance"]),
    )
    if movement > float(settings["tolerance"]):
        raise ValueError("reconstructed context clustering did not converge")
    machine_ids = []
    for centroid in centroids:
        digest = hashlib.sha256(
            (payload_hash(contract) + canonical_json(np.round(centroid, 8).tolist())).encode("utf-8")
        ).hexdigest()[:12]
        machine_ids.append(f"EURUSD_CONTEXT_V1_{digest}")
    expected = {row["machine_cluster_id"] for row in discovery.get("clusters") or []}
    if set(machine_ids) != expected:
        raise ValueError("reconstructed context IDs do not match the pinned discovery run")
    labels = _nearest_centroid_labels(standardized, centroids)
    return np.asarray([machine_ids[index] for index in labels])


def _trade_outcome(
    pack: dict[str, np.ndarray],
    signal_index: int,
    direction: str,
    horizon: int,
    target_r: float,
    fixed_cost_pips: float,
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
    risk = max(8.0 * PIP_SIZE, atr)
    sign = 1.0 if direction == "LONG" else -1.0
    if direction == "LONG":
        stop, target = entry - risk, entry + target_r * risk
    elif direction == "SHORT":
        stop, target = entry + risk, entry - target_r * risk
    else:
        raise ValueError(f"unsupported context direction: {direction}")
    exit_price = float(pack["close"][final_index])
    exit_reason = "HORIZON"
    gross_r = None
    maximum_favorable_r = -math.inf
    maximum_adverse_r = math.inf
    exit_index = final_index
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
        elif favorable_gap:
            exit_price = target
            gross_r = target_r
            exit_reason = "TARGET_GAP_CONSERVATIVE"
        elif stop_touched:
            exit_price = stop
            gross_r = -1.0
            exit_reason = "STOP"
        elif target_touched:
            exit_price = target
            gross_r = target_r
            exit_reason = "TARGET"
        else:
            continue
        exit_index = index
        break
    if gross_r is None:
        gross_r = sign * (exit_price - entry) / risk
    stop_distance_pips = risk / PIP_SIZE
    cost_r = fixed_cost_pips / stop_distance_pips
    return {
        "entry_time_utc": _iso(float(pack["time"][entry_index])),
        "exit_time_utc": _iso(float(pack["end"][exit_index])),
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
        raise ValueError("unsupported context discovery report")
    if sha256_file(discovery_path) != predeclaration.get("source_discovery_report_sha256"):
        raise ValueError("context discovery report no longer matches the predeclaration")
    for table, id_column, record_id, payload in (
        ("context_predeclarations", "predeclaration_id", predeclaration["predeclaration_id"], predeclaration),
        ("context_evaluation_protocols", "protocol_id", protocol["protocol_id"], protocol),
    ):
        row = connection.execute(
            f"SELECT payload_hash FROM {table} WHERE {id_column}=?", (record_id,)
        ).fetchone()
        if row is None or row["payload_hash"] != payload_hash(payload):
            raise ValueError(f"exact registered record required before evaluation: {table}:{record_id}")
    metadata, arrays = _load_matrix(matrix_metadata_path)
    if metadata.get("artifact_id") != predeclaration.get("source_matrix_artifact_id"):
        raise ValueError("context matrix does not match the predeclaration")
    assignments = _cluster_assignments(arrays["values"], contract, discovery)
    development_times = arrays["times"]
    source_rows, _ = _load_context_rows(connection, inbox_dir, contract)
    pack = _series_pack(source_rows["EURUSD_M15"])
    development_end = parse_utc(contract["development"]["end_utc_exclusive"])
    target_r = float(predeclaration["execution_geometry"]["target_r"])
    cost = float(predeclaration["cost_model"]["fixed_round_trip_cost_pips"])
    horizons = [int(value) for value in predeclaration["execution_geometry"]["horizon_bars"]]
    all_event_rows: list[dict[str, Any]] = []
    hypothesis_rows: list[dict[str, Any]] = []
    raw_p_values: list[float] = []
    min_events = int(predeclaration["objective_gates"]["minimum_independent_events_per_primary_hypothesis"])
    test = protocol["significance_test"]
    for context_offset, context in enumerate(predeclaration["selected_contexts"]):
        event_indices = _independent_event_indices(assignments, context["machine_cluster_id"])
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
                primary = _trade_outcome(pack, signal_index, context["direction"], horizon, target_r, cost, development_end)
                opposite_direction = "SHORT" if context["direction"] == "LONG" else "LONG"
                opposite = _trade_outcome(pack, signal_index, opposite_direction, horizon, target_r, cost, development_end)
                shifted = _trade_outcome(pack, shifted_signal_index, context["direction"], horizon, target_r, cost, development_end)
                if primary is None or opposite is None or shifted is None:
                    continue
                record = {
                    "context_id": context["machine_cluster_id"],
                    "mechanism_label": context["mechanism_label"],
                    "direction": context["direction"],
                    "horizon_bars": horizon,
                    "decision_time_utc": str(development_times[event_index]),
                    "shifted_control_decision_time_utc": str(development_times[shifted_index]),
                    "primary": primary,
                    "opposite_direction_control": opposite,
                    "shifted_event_control": shifted,
                }
                records.append(record)
                all_event_rows.append(record)
            metric_rows = [{
                "decision_time_utc": row["decision_time_utc"],
                "primary_net_r": row["primary"]["net_r"],
                "opposite_net_r": row["opposite_direction_control"]["net_r"],
                "shifted_net_r": row["shifted_event_control"]["net_r"],
            } for row in records]
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
                    seed=int(test["seed"]) + context_offset * 100 + horizon,
                )
            raw_p_values.append(p_value)
            hypothesis_rows.append({
                "hypothesis_id": f"{context['machine_cluster_id']}_{context['direction']}_H{horizon}",
                "context_id": context["machine_cluster_id"],
                "mechanism_label": context["mechanism_label"],
                "direction": context["direction"],
                "horizon_bars": horizon,
                "primary": primary_metrics,
                "opposite_direction_control": opposite_metrics,
                "shifted_event_control": shifted_metrics,
                "paired_edge_over_stronger_control_average_r": round(float(np.mean(differences)), 8) if len(differences) else None,
                "raw_sign_flip_p_value": round(float(p_value), 10),
            })
    planned = int(predeclaration["planned_confirmation_budget"]["planned_primary_hypothesis_count"])
    if len(hypothesis_rows) != planned:
        raise ValueError("executed context hypothesis count differs from the sealed budget")
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
    run_id = f"CONTEXT_DEVELOPMENT_EVALUATION_{hashlib.sha256(canonical_json(run_seed).encode()).hexdigest()[:20]}"
    output_dir.mkdir(parents=True, exist_ok=True)
    event_path = output_dir / f"{run_id}.events.json.gz"
    _write_gzip_json(event_path, event_payload)
    report = {
        "schema": EVALUATION_SCHEMA,
        "evaluation_run_id": run_id,
        "created_at_utc": protocol["created_at_utc"],
        "status": "DEVELOPMENT_SURVIVORS_REQUIRE_SEALED_VALIDATION_APPROVAL" if survivor_count else "NO_DEVELOPMENT_SURVIVORS",
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
        "next_gate": "HUMAN_REVIEW_BEFORE_ANY_SEALED_VALIDATION_ACCESS" if survivor_count else "ARCHIVE_RESULT_WITHOUT_RETUNING",
    }
    write_json_atomic(output_dir / f"{run_id}.json", report)
    write_json_atomic(output_dir / "latest_development_evaluation.json", report)
    insert_immutable(
        connection,
        "context_evaluation_runs",
        "evaluation_run_id",
        run_id,
        report,
        {"created_at_utc": protocol["created_at_utc"]},
    )
    return report
