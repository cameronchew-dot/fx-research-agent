from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from .experiments import _load_evidence


RESULT_SCHEMA = "FX_CME_AGENT_CONTEXT_DIAGNOSTIC_RESULT_V1"
BASE_NUMERIC = (
    "spread_to_atr",
    "maximum_touch_index",
    "reward_room_r",
    "daily_atr_consumed_fraction",
)
BASE_BINARY = (
    "direction_long",
    "htf_aligned",
    "htf_opposed",
    "htf_mixed",
    "session_asia",
    "session_london",
    "session_london_ny_overlap",
    "session_ny_afternoon",
    "session_rollover_late",
    "macro_blackout",
)
CME_FEATURES = (
    "cme_directional_return_15m_bps",
    "cme_directional_close_location",
    "cme_log_volume_ratio",
    "cme_log_range_ratio",
    "cme_directional_return_60m_bps",
    "cme_log_realized_volatility_ratio",
)


def _utc(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_episode_rows(
    database_path: Path,
    evidence_inbox: Path,
    campaign: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    uri = f"file:{database_path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        evidence = _load_evidence(connection, evidence_inbox, campaign["instrument"])
    finally:
        connection.close()

    population = campaign["population"]
    outcomes_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for outcome in evidence["outcomes"].values():
        outcomes_by_candidate.setdefault(str(outcome.get("candidate_id")), []).append(outcome)

    eligible: list[dict[str, Any]] = []
    for candidate_id, candidate in evidence["candidates"].items():
        if candidate.get("mechanism_class") != population["mechanism_class"]:
            continue
        decision_time = str(candidate.get("decision_time_utc") or "")
        if not decision_time or decision_time > population["maximum_decision_time_utc"]:
            continue
        matching = []
        for outcome in outcomes_by_candidate.get(candidate_id, []):
            if outcome.get("arm_id") != population["arm_id"]:
                continue
            if outcome.get("entry_model") != population["entry_model"]:
                continue
            if int(outcome.get("horizon_bars") or -1) != int(population["horizon_m15_bars"]):
                continue
            if float(outcome.get("target_r") or -1) != float(population["target_r"]):
                continue
            if outcome.get("same_bar_tie_policy") != population["same_bar_tie_policy"]:
                continue
            if outcome.get("realized_net_r") is None:
                continue
            matching.append(outcome)
        if not matching:
            continue
        outcome = min(
            matching,
            key=lambda row: (str(row.get("observed_at_utc") or ""), str(row.get("outcome_id") or "")),
        )
        context = evidence["contexts"].get(candidate_id) or {}
        market = candidate.get("market_facts") or {}
        objective_levels = candidate.get("objective_levels") or []
        maximum_touch = max(
            (int(row.get("touch_index") or 0) for row in objective_levels),
            default=0,
        )
        atr_pips = float(market.get("atr_pips") or 0.0)
        spread_pips = float(market.get("spread_pips") or 0.0)
        direction = str(candidate.get("direction") or "")
        htf = str(market.get("htf_alignment") or "NEUTRAL")
        session = str(market.get("session_bucket") or "UNKNOWN")
        target_room = context.get("target_room") or {}
        daily_range = context.get("daily_range") or {}
        eligible.append(
            {
                "candidate_id": candidate_id,
                "episode_id": str(candidate.get("episode_id") or candidate_id),
                "decision_time_utc": decision_time,
                "direction": direction,
                "realized_net_r": float(outcome["realized_net_r"]),
                "positive_label": int(float(outcome["realized_net_r"]) > 0.0),
                "spread_to_atr": spread_pips / atr_pips if atr_pips > 0 else None,
                "maximum_touch_index": maximum_touch,
                "reward_room_r": target_room.get("reward_room_r"),
                "daily_atr_consumed_fraction": daily_range.get("atr_consumed_fraction"),
                "direction_long": int(direction == "LONG"),
                "htf_aligned": int(htf == "ALIGNED"),
                "htf_opposed": int(htf == "OPPOSED"),
                "htf_mixed": int(htf == "MIXED"),
                "session_asia": int(session == "ASIA"),
                "session_london": int(session == "LONDON"),
                "session_london_ny_overlap": int(session == "LONDON_NY_OVERLAP"),
                "session_ny_afternoon": int(session == "NY_AFTERNOON"),
                "session_rollover_late": int(session == "ROLLOVER_LATE"),
                "macro_blackout": int(market.get("macro_blackout_state") == "BLACKOUT"),
            }
        )

    first_by_episode: dict[str, dict[str, Any]] = {}
    for row in sorted(
        eligible,
        key=lambda value: (value["decision_time_utc"], value["candidate_id"]),
    ):
        first_by_episode.setdefault(row["episode_id"], row)

    independent = []
    next_available = datetime.min.replace(tzinfo=timezone.utc)
    horizon = timedelta(minutes=15 * int(population["horizon_m15_bars"]))
    for row in first_by_episode.values():
        decision = datetime.fromisoformat(row["decision_time_utc"].replace("Z", "+00:00"))
        if decision < next_available:
            continue
        independent.append(row)
        next_available = decision + horizon
    return independent, evidence["manifest_ids"]


def build_futures_features(
    path: Path,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    minimum_source_minutes: int = 10,
) -> pd.DataFrame:
    dataset = ds.dataset(path)
    predicate = (
        (ds.field("event_time_utc") >= start.to_pydatetime())
        & (ds.field("event_time_utc") < end.to_pydatetime())
    )
    table = dataset.to_table(
        filter=predicate,
        columns=[
            "event_time_utc",
            "adjusted_open",
            "adjusted_high",
            "adjusted_low",
            "adjusted_close",
            "volume",
        ],
    )
    minute = table.to_pandas()
    minute["event_time_utc"] = pd.to_datetime(minute["event_time_utc"], utc=True)
    minute.sort_values("event_time_utc", inplace=True)
    minute.set_index("event_time_utc", inplace=True)
    minute["log_return"] = np.log(minute["adjusted_close"] / minute["adjusted_close"].shift(1))
    minute["squared_log_return"] = minute["log_return"].pow(2)
    grouped = minute.resample("15min", label="left", closed="left")
    bars = grouped.agg(
        open=("adjusted_open", "first"),
        high=("adjusted_high", "max"),
        low=("adjusted_low", "min"),
        close=("adjusted_close", "last"),
        volume=("volume", "sum"),
        source_minutes=("adjusted_close", "count"),
        squared_return_sum=("squared_log_return", "sum"),
    )
    bars = bars[bars["source_minutes"] >= minimum_source_minutes].copy()
    bars["available_at_utc"] = bars.index + pd.Timedelta(minutes=15)
    previous_close = bars["close"].shift(1)
    bars["true_range"] = pd.concat(
        [
            bars["high"] - bars["low"],
            (bars["high"] - previous_close).abs(),
            (bars["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    price_range = bars["high"] - bars["low"]
    bars["return_15m_bps"] = (bars["close"] / bars["open"] - 1.0) * 10000.0
    bars["close_location"] = np.where(
        price_range > 0,
        2.0 * (bars["close"] - bars["low"]) / price_range - 1.0,
        0.0,
    )
    bars["return_60m_bps"] = (bars["close"] / bars["close"].shift(4) - 1.0) * 10000.0
    bars["realized_volatility_bps"] = np.sqrt(bars["squared_return_sum"]) * 10000.0
    local = bars.index.tz_convert("America/New_York")
    bars["local_slot"] = local.hour * 4 + local.minute // 15
    for source, baseline, ratio in (
        ("volume", "volume_baseline", "volume_ratio"),
        ("true_range", "range_baseline", "range_ratio"),
        ("realized_volatility_bps", "volatility_baseline", "volatility_ratio"),
    ):
        bars[baseline] = bars.groupby("local_slot", group_keys=False)[source].transform(
            lambda values: values.shift(1).rolling(20, min_periods=20).median()
        )
        bars[ratio] = bars[source] / bars[baseline].replace(0.0, np.nan)
    bars.set_index("available_at_utc", inplace=True, drop=False)
    return bars


def join_cme_features(
    episodes: list[dict[str, Any]],
    futures: pd.DataFrame,
) -> list[dict[str, Any]]:
    output = []
    for source in episodes:
        decision = _utc(source["decision_time_utc"])
        if decision not in futures.index:
            continue
        current = futures.loc[decision]
        if isinstance(current, pd.DataFrame):
            current = current.iloc[-1]
        lag_time = decision - pd.Timedelta(hours=24)
        lagged = futures.loc[lag_time] if lag_time in futures.index else None
        if isinstance(lagged, pd.DataFrame):
            lagged = lagged.iloc[-1]
        direction = 1.0 if source["direction"] == "LONG" else -1.0

        def features(row: pd.Series | None, prefix: str) -> dict[str, float | None]:
            if row is None:
                return {f"{prefix}{name.removeprefix('cme_')}": None for name in CME_FEATURES}
            ratios = {
                "cme_log_volume_ratio": row.get("volume_ratio"),
                "cme_log_range_ratio": row.get("range_ratio"),
                "cme_log_realized_volatility_ratio": row.get("volatility_ratio"),
            }
            values: dict[str, float | None] = {
                "cme_directional_return_15m_bps": direction * float(row["return_15m_bps"]),
                "cme_directional_close_location": direction * float(row["close_location"]),
                "cme_directional_return_60m_bps": direction * float(row["return_60m_bps"]),
            }
            for name, value in ratios.items():
                values[name] = (
                    float(np.clip(math.log(float(value)), -3.0, 3.0))
                    if value is not None and pd.notna(value) and float(value) > 0
                    else None
                )
            return {f"{prefix}{name.removeprefix('cme_')}": value for name, value in values.items()}

        current_values = features(current, "cme_")
        lagged_values = features(lagged, "cme_lag24h_")
        if any(current_values[name] is None or not math.isfinite(float(current_values[name])) for name in CME_FEATURES):
            continue
        output.append({**source, **current_values, **lagged_values})
    return output


def _transform(
    train_rows: list[dict[str, Any]],
    predict_rows: list[dict[str, Any]],
    features: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray]:
    train = np.asarray(
        [[np.nan if row.get(name) is None else float(row[name]) for name in features] for row in train_rows],
        dtype=float,
    )
    predict = np.asarray(
        [[np.nan if row.get(name) is None else float(row[name]) for name in features] for row in predict_rows],
        dtype=float,
    )
    medians = np.nanmedian(train, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    train = np.where(np.isnan(train), medians, train)
    predict = np.where(np.isnan(predict), medians, predict)
    means = train.mean(axis=0)
    deviations = train.std(axis=0)
    deviations = np.where(deviations > 1e-12, deviations, 1.0)
    return (train - means) / deviations, (predict - means) / deviations


def fit_logistic_predict(
    train_rows: list[dict[str, Any]],
    predict_rows: list[dict[str, Any]],
    features: tuple[str, ...],
    *,
    l2_penalty: float = 1.0,
) -> np.ndarray:
    x_train, x_predict = _transform(train_rows, predict_rows, features)
    x_train = np.column_stack([np.ones(len(x_train)), x_train])
    x_predict = np.column_stack([np.ones(len(x_predict)), x_predict])
    y = np.asarray([row["positive_label"] for row in train_rows], dtype=float)
    weights = np.zeros(x_train.shape[1], dtype=float)
    penalty = np.eye(x_train.shape[1]) * l2_penalty
    penalty[0, 0] = 0.0
    for _ in range(60):
        logits = np.clip(x_train @ weights, -30.0, 30.0)
        probability = 1.0 / (1.0 + np.exp(-logits))
        gradient = x_train.T @ (probability - y) + penalty @ weights
        curvature = probability * (1.0 - probability)
        hessian = x_train.T @ (x_train * curvature[:, None]) + penalty
        hessian += np.eye(hessian.shape[0]) * 1e-8
        step = np.linalg.solve(hessian, gradient)
        weights -= step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    logits = np.clip(x_predict @ weights, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-logits))


def roc_auc(labels: list[int], probabilities: list[float]) -> float | None:
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(zip(probabilities, labels), key=lambda row: row[0])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        rank_sum += average_rank * sum(label for _, label in ordered[index:end])
        index = end
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def metric_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    probabilities = [float(row[key]) for row in rows]
    labels = [int(row["positive_label"]) for row in rows]
    clipped = np.clip(np.asarray(probabilities), 1e-9, 1.0 - 1e-9)
    label_array = np.asarray(labels, dtype=float)
    order = np.argsort(clipped)
    tercile = max(1, len(rows) // 3)
    bottom = [rows[int(index)]["realized_net_r"] for index in order[:tercile]]
    top = [rows[int(index)]["realized_net_r"] for index in order[-tercile:]]
    auc = roc_auc(labels, probabilities)
    return {
        "prediction_count": len(rows),
        "positive_count": sum(labels),
        "positive_rate": float(np.mean(label_array)) if len(rows) else None,
        "roc_auc": round(float(auc), 8) if auc is not None else None,
        "brier_score": round(float(np.mean((clipped - label_array) ** 2)), 8) if len(rows) else None,
        "log_loss": round(
            float(-np.mean(label_array * np.log(clipped) + (1.0 - label_array) * np.log(1.0 - clipped))),
            8,
        ) if len(rows) else None,
        "top_tercile_average_net_r": round(float(np.mean(top)), 8) if top else None,
        "bottom_tercile_average_net_r": round(float(np.mean(bottom)), 8) if bottom else None,
    }


def walk_forward_predictions(
    rows: list[dict[str, Any]],
    *,
    minimum_training: int,
    l2_penalty: float,
) -> list[dict[str, Any]]:
    baseline_features = (*BASE_NUMERIC, *BASE_BINARY)
    enhanced_features = (*baseline_features, *CME_FEATURES)
    lagged_features = (
        *baseline_features,
        *(f"cme_lag24h_{name.removeprefix('cme_')}" for name in CME_FEATURES),
    )
    predictions = []
    for index in range(minimum_training, len(rows)):
        train = rows[:index]
        current = [rows[index]]
        predictions.append(
            {
                **rows[index],
                "spot_probability": float(
                    fit_logistic_predict(train, current, baseline_features, l2_penalty=l2_penalty)[0]
                ),
                "cme_probability": float(
                    fit_logistic_predict(train, current, enhanced_features, l2_penalty=l2_penalty)[0]
                ),
                "lag24h_probability": float(
                    fit_logistic_predict(train, current, lagged_features, l2_penalty=l2_penalty)[0]
                ),
                "prior_training_episode_count": index,
            }
        )
    return predictions


def _metric_delta(candidate: dict[str, Any], reference: dict[str, Any]) -> dict[str, float | None]:
    return {
        "roc_auc": (
            round(float(candidate["roc_auc"] - reference["roc_auc"]), 8)
            if candidate["roc_auc"] is not None and reference["roc_auc"] is not None
            else None
        ),
        "brier_score": round(float(candidate["brier_score"] - reference["brier_score"]), 8),
        "log_loss": round(float(candidate["log_loss"] - reference["log_loss"]), 8),
    }


def evaluate(
    root: Path,
    campaign: dict[str, Any],
) -> dict[str, Any]:
    episodes, evidence_manifests = load_episode_rows(
        root / "data" / "fx_research_agent.sqlite3",
        root / "data" / "evidence_inbox",
        campaign,
    )
    if not episodes:
        raise ValueError("no eligible independent episodes")
    decisions = [_utc(row["decision_time_utc"]) for row in episodes]
    build_id = campaign["futures_source"]["continuous_build_id"]
    build_root = root / "data" / "derived" / "databento_continuous" / "6E" / build_id
    futures = build_futures_features(
        build_root / "continuous_bars_1m.parquet",
        start=min(decisions) - pd.Timedelta(days=45),
        end=max(decisions) + pd.Timedelta(minutes=1),
        minimum_source_minutes=int(campaign["causal_join"]["minimum_source_minutes"]),
    )
    joined = join_cme_features(episodes, futures)
    model = campaign["locked_model"]
    predictions = walk_forward_predictions(
        joined,
        minimum_training=int(model["minimum_initial_training_episodes"]),
        l2_penalty=float(model["l2_penalty"]),
    )
    dated_start = int(len(predictions) * 0.8)
    dated = predictions[dated_start:]
    all_metrics = {
        "spot": metric_summary(predictions, "spot_probability"),
        "cme": metric_summary(predictions, "cme_probability"),
        "lag24h": metric_summary(predictions, "lag24h_probability"),
    }
    dated_metrics = {
        "spot": metric_summary(dated, "spot_probability"),
        "cme": metric_summary(dated, "cme_probability"),
        "lag24h": metric_summary(dated, "lag24h_probability"),
    }
    lift_spot = _metric_delta(all_metrics["cme"], all_metrics["spot"])
    lift_lag = _metric_delta(all_metrics["cme"], all_metrics["lag24h"])
    dated_lift_spot = _metric_delta(dated_metrics["cme"], dated_metrics["spot"])
    gates = campaign["review_gates"]
    checks = {
        "minimum_independent_joined_episodes": len(joined) >= int(gates["minimum_independent_joined_episodes"]),
        "minimum_walk_forward_predictions": len(predictions) >= int(gates["minimum_walk_forward_predictions"]),
        "minimum_dated_tail_predictions": len(dated) >= int(gates["minimum_dated_tail_predictions"]),
        "minimum_auc_lift_over_spot": lift_spot["roc_auc"] is not None and lift_spot["roc_auc"] >= float(gates["minimum_auc_lift_over_spot"]),
        "brier_improves_over_spot": lift_spot["brier_score"] < 0,
        "log_loss_improves_over_spot": lift_spot["log_loss"] < 0,
        "beats_24h_lag_control": (
            lift_lag["roc_auc"] is not None and lift_lag["roc_auc"] > 0
            and lift_lag["brier_score"] < 0 and lift_lag["log_loss"] < 0
        ),
        "dated_tail_metric_directions_agree": (
            dated_lift_spot["roc_auc"] is not None and dated_lift_spot["roc_auc"] > 0
            and dated_lift_spot["brier_score"] < 0 and dated_lift_spot["log_loss"] < 0
        ),
        "top_tercile_average_net_r_exceeds_bottom": (
            all_metrics["cme"]["top_tercile_average_net_r"]
            > all_metrics["cme"]["bottom_tercile_average_net_r"]
        ),
    }
    blocks = [name for name, passed in checks.items() if not passed]
    result_rows = [
        {
            key: row[key]
            for key in (
                "candidate_id", "episode_id", "decision_time_utc", "direction",
                "realized_net_r", "positive_label", "spot_probability",
                "cme_probability", "lag24h_probability", "prior_training_episode_count",
            )
        }
        for row in predictions
    ]
    manifest_path = build_root / "6e.causal-continuous.market.manifest.json"
    return {
        "schema": RESULT_SCHEMA,
        "campaign_id": campaign["campaign_id"],
        "status": "DIAGNOSTIC_GATE_PASS_REQUIRES_FRESH_FORWARD_CONFIRMATION" if not blocks else "DIAGNOSTIC_GATE_FAIL",
        "evidence_role": campaign["evidence_role"],
        "population": {
            "episode_unique_before_nonoverlap": None,
            "independent_episode_count": len(episodes),
            "cme_joined_episode_count": len(joined),
            "walk_forward_prediction_count": len(predictions),
            "dated_tail_prediction_count": len(dated),
            "window_start_utc": joined[0]["decision_time_utc"] if joined else None,
            "window_end_utc": joined[-1]["decision_time_utc"] if joined else None,
        },
        "metrics": all_metrics,
        "cme_minus_spot": lift_spot,
        "cme_minus_lag24h": lift_lag,
        "dated_tail_metrics": dated_metrics,
        "dated_cme_minus_spot": dated_lift_spot,
        "gates": checks,
        "gate_blocks": blocks,
        "feature_coverage": len(joined) / len(episodes),
        "provenance": {
            "campaign_sha256": hashlib.sha256(
                json.dumps(campaign, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "evidence_manifest_count": len(evidence_manifests),
            "evidence_manifest_ids_sha256": hashlib.sha256(
                json.dumps(evidence_manifests, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "cme_manifest_path": str(manifest_path.relative_to(root)),
            "cme_manifest_sha256": sha256_file(manifest_path),
        },
        "prediction_rows": result_rows,
        "automatic_agent_context_activation": False,
        "automatic_signal_activation": False,
        "paper_or_live_authority": False,
    }
