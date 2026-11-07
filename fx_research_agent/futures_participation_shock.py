from __future__ import annotations

import hashlib
import math
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .futures_context_research import (
    PAIR_TO_PRODUCT,
    _iso,
    _metrics,
    _outcome,
    _utc,
    load_futures_m15,
    load_spot_m15,
)
from .motif_evaluation import _holm_adjust, _sign_flip_p_value, instrument_pip_size


RESULT_SCHEMA = "FX_MULTIPAIR_CME_PARTICIPATION_SHOCK_DEVELOPMENT_RESULT_V1"
ACCEPTANCE = "VOLUME_RANGE_SHOCK_ACCEPTANCE_CONTINUATION"
REVERSAL = "VOLUME_RANGE_SHOCK_FAILED_AUCTION_REVERSAL"
MECHANISMS = (ACCEPTANCE, REVERSAL)


def classify_participation_shock(row: pd.Series, prior_close: float) -> tuple[str, str] | None:
    required = ("volume_ratio", "range_ratio", "source_minutes", "high", "low", "open", "close")
    if any(pd.isna(row.get(field)) for field in required):
        return None
    if int(row["source_minutes"]) < 10 or float(row["volume_ratio"]) < 1.75 or float(row["range_ratio"]) < 1.5:
        return None
    high, low = float(row["high"]), float(row["low"])
    if high <= low or not math.isfinite(prior_close):
        return None
    close_location = (float(row["close"]) - low) / (high - low)
    up_extension = high - prior_close
    down_extension = prior_close - low
    attempted_up = up_extension > down_extension
    if attempted_up and close_location >= 0.75 and float(row["close"]) > float(row["open"]):
        return ACCEPTANCE, "LONG"
    if not attempted_up and close_location <= 0.25 and float(row["close"]) < float(row["open"]):
        return ACCEPTANCE, "SHORT"
    if attempted_up and close_location <= 0.35:
        return REVERSAL, "SHORT"
    if not attempted_up and close_location >= 0.65:
        return REVERSAL, "LONG"
    return None


def _spot_atr14(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.shift(1).rolling(14, min_periods=14).mean()


def _geometry_outcome(
    spot: pd.DataFrame,
    entry_index: int,
    direction: str,
    risk: float,
    *,
    target_r: float,
    horizon: int,
    cost_pips: float,
    pip_size: float,
) -> dict[str, Any]:
    entry = float(spot.at[entry_index, "open"])
    sign = 1.0 if direction == "LONG" else -1.0
    return _outcome(
        spot,
        entry_index,
        direction,
        stop=entry - sign * risk,
        target=entry + sign * target_r * risk,
        risk=risk,
        horizon=horizon,
        cost_pips=cost_pips,
        pip_size=pip_size,
    )


def build_instrument_events(
    spot: pd.DataFrame,
    futures: pd.DataFrame,
    instrument: str,
    specification: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    spot = spot.copy().reset_index(drop=True)
    spot["atr14"] = _spot_atr14(spot)
    spot_by_end = {pd.Timestamp(value): index for index, value in enumerate(spot["end_time"])}
    pip_size = instrument_pip_size(instrument)
    execution = specification["spot_execution"]
    target_r = float(execution["target_r"])
    horizon = int(execution["maximum_horizon_m15_bars"])
    cost_pips = float(execution["fixed_round_trip_cost_pips"][instrument])
    output: dict[str, list[dict[str, Any]]] = {mechanism: [] for mechanism in MECHANISMS}
    seen: dict[str, set[tuple[str, str]]] = {mechanism: set() for mechanism in MECHANISMS}
    last_final: dict[str, int] = {mechanism: -1 for mechanism in MECHANISMS}
    futures = futures.sort_index().copy()
    futures["prior_close"] = futures["close"].shift(1)
    for _, future in futures.iterrows():
        classification = classify_participation_shock(future, float(future["prior_close"]))
        if classification is None:
            continue
        mechanism, direction = classification
        key = (str(future["session_date"]), direction)
        if key in seen[mechanism]:
            continue
        decision = pd.Timestamp(future["end_time"])
        decision_index = spot_by_end.get(decision)
        if decision_index is None:
            continue
        entry_index = decision_index + 1
        delayed_entry_index = decision_index + 5
        if delayed_entry_index + horizon - 1 >= len(spot) or entry_index <= last_final[mechanism]:
            continue
        atr = float(spot.at[decision_index, "atr14"])
        if not math.isfinite(atr) or atr <= 0:
            continue
        risk = max(atr, 5.0 * pip_size)
        opposite_direction = "SHORT" if direction == "LONG" else "LONG"
        primary = _geometry_outcome(
            spot,
            entry_index,
            direction,
            risk,
            target_r=target_r,
            horizon=horizon,
            cost_pips=cost_pips,
            pip_size=pip_size,
        )
        opposite = _geometry_outcome(
            spot,
            entry_index,
            opposite_direction,
            risk,
            target_r=target_r,
            horizon=horizon,
            cost_pips=cost_pips,
            pip_size=pip_size,
        )
        delayed = _geometry_outcome(
            spot,
            delayed_entry_index,
            direction,
            risk,
            target_r=target_r,
            horizon=horizon,
            cost_pips=cost_pips,
            pip_size=pip_size,
        )
        last_final[mechanism] = int(primary["final_index"])
        seen[mechanism].add(key)
        identity = f"{instrument}|{mechanism}|{direction}|{_iso(decision)}"
        output[mechanism].append(
            {
                "event_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
                "instrument": instrument,
                "mechanism": mechanism,
                "direction": direction,
                "decision_time_utc": _iso(decision),
                "cme_session_date": str(future["session_date"]),
                "futures_volume_ratio": round(float(future["volume_ratio"]), 8),
                "futures_range_ratio": round(float(future["range_ratio"]), 8),
                "futures_close_location": round(
                    (float(future["close"]) - float(future["low"]))
                    / (float(future["high"]) - float(future["low"])),
                    8,
                ),
                "spot_atr14_pips": round(atr / pip_size, 6),
                "primary_net_r": primary["net_r"],
                "opposite_net_r": opposite["net_r"],
                "delayed_net_r": delayed["net_r"],
                "net_r": primary["net_r"],
                "mfe_r": primary["mfe_r"],
                "mae_r": primary["mae_r"],
                "primary": {key: value for key, value in primary.items() if key not in {"entry_index", "final_index"}},
                "opposite_direction_control": {
                    key: value for key, value in opposite.items() if key not in {"entry_index", "final_index"}
                },
                "delayed_entry_control": {
                    key: value for key, value in delayed.items() if key not in {"entry_index", "final_index"}
                },
            }
        )
    return output


def _control_metrics(rows: list[dict[str, Any]], key: str, outcome_key: str) -> dict[str, Any]:
    converted = [
        {
            **row,
            "net_r": row[key],
            "mfe_r": row[outcome_key]["mfe_r"],
            "mae_r": row[outcome_key]["mae_r"],
        }
        for row in rows
    ]
    return _metrics(converted)


def _gate_blocks(summary: dict[str, Any], gates: dict[str, Any]) -> list[str]:
    checks = (
        (summary["event_count"] >= gates["minimum_pooled_independent_events"], "INSUFFICIENT_EVENTS"),
        (summary["calendar_month_count"] >= gates["minimum_calendar_months_with_events"], "INSUFFICIENT_MONTHS"),
        (summary["average_net_r"] is not None and summary["average_net_r"] >= gates["minimum_average_net_r"], "AVERAGE_NET_R_BELOW_MIN"),
        (summary["median_net_r"] is not None and summary["median_net_r"] > gates["minimum_median_net_r_exclusive"], "MEDIAN_NET_R_NOT_POSITIVE"),
        (summary["positive_net_r_rate"] is not None and summary["positive_net_r_rate"] >= gates["minimum_positive_net_r_rate"], "POSITIVE_RATE_BELOW_MIN"),
        (summary["positive_month_rate"] is not None and summary["positive_month_rate"] >= gates["minimum_positive_month_rate"], "POSITIVE_MONTH_RATE_BELOW_MIN"),
        (summary["worst_month_average_net_r"] is not None and summary["worst_month_average_net_r"] >= gates["minimum_worst_month_average_net_r"], "WORST_MONTH_BELOW_MIN"),
        (summary["top_five_percent_positive_r_contribution_fraction"] <= gates["maximum_top_five_percent_positive_r_contribution_fraction"], "OUTLIER_DEPENDENCE_ABOVE_MAX"),
        (summary["paired_edge_over_opposite_direction_r"] >= gates["minimum_paired_average_net_r_edge_over_each_control"], "OPPOSITE_CONTROL_EDGE_BELOW_MIN"),
        (summary["paired_edge_over_delayed_entry_r"] >= gates["minimum_paired_average_net_r_edge_over_each_control"], "DELAYED_CONTROL_EDGE_BELOW_MIN"),
        (summary["holm_adjusted_p_value"] <= gates["holm_adjusted_p_value_maximum"], "HOLM_SIGNIFICANCE_NOT_CLEAR"),
    )
    return [label for passed, label in checks if not passed]


def evaluate_development(
    root: Path,
    campaign: dict[str, Any],
    *,
    draws: int = 20000,
    seed: int = 20261108,
) -> dict[str, Any]:
    start = _utc(campaign["population"]["common_history_start_inclusive"])
    development_end = _utc(campaign["population"]["development_decision_time_end_exclusive"])
    events: dict[str, dict[str, list[dict[str, Any]]]] = {}
    pooled: dict[str, list[dict[str, Any]]] = {mechanism: [] for mechanism in MECHANISMS}
    for instrument in campaign["instruments"]:
        product = PAIR_TO_PRODUCT[instrument]
        build_id = campaign["futures_build_ids"][product]
        spot = load_spot_m15(
            root / "data" / "inbox",
            campaign["source_manifest_ids"][instrument],
            instrument,
            start=start,
            end=development_end,
        )
        futures = load_futures_m15(
            root / "data" / "derived" / "databento_continuous" / product / build_id / "continuous_bars_1m.parquet",
            start=start - timedelta(days=40),
            end=development_end,
        )
        instrument_events = build_instrument_events(spot, futures, instrument, campaign["exact_specification"])
        events[instrument] = instrument_events
        for mechanism in MECHANISMS:
            pooled[mechanism].extend(instrument_events[mechanism])
    summaries = []
    raw_p_values = []
    for mechanism_index, mechanism in enumerate(MECHANISMS):
        rows = sorted(pooled[mechanism], key=lambda row: (row["decision_time_utc"], row["instrument"]))
        primary = _metrics(rows)
        opposite = _control_metrics(rows, "opposite_net_r", "opposite_direction_control")
        delayed = _control_metrics(rows, "delayed_net_r", "delayed_entry_control")
        primary["paired_edge_over_opposite_direction_r"] = round(
            float(np.mean([row["primary_net_r"] - row["opposite_net_r"] for row in rows])), 8
        ) if rows else None
        primary["paired_edge_over_delayed_entry_r"] = round(
            float(np.mean([row["primary_net_r"] - row["delayed_net_r"] for row in rows])), 8
        ) if rows else None
        differences = np.asarray(
            [row["primary_net_r"] - max(row["opposite_net_r"], row["delayed_net_r"]) for row in rows],
            dtype=float,
        )
        p_value = _sign_flip_p_value(differences, draws=draws, seed=seed + mechanism_index) if len(differences) else 1.0
        raw_p_values.append(p_value)
        summaries.append(
            {
                "mechanism": mechanism,
                "primary": primary,
                "opposite_direction_control": opposite,
                "delayed_entry_control": delayed,
                "pair_breakdown_descriptive_only": {
                    instrument: _metrics([row for row in rows if row["instrument"] == instrument])
                    for instrument in campaign["instruments"]
                },
                "raw_sign_flip_p_value": round(float(p_value), 10),
            }
        )
    adjusted = _holm_adjust(raw_p_values)
    survivor_count = 0
    for summary, adjusted_p in zip(summaries, adjusted):
        summary["primary"]["holm_adjusted_p_value"] = round(float(adjusted_p), 10)
        blocks = _gate_blocks(summary["primary"], campaign["review_gates"])
        summary["gate_blocks"] = blocks
        summary["development_survivor"] = not blocks
        survivor_count += int(not blocks)
    return {
        "schema": RESULT_SCHEMA,
        "campaign_id": campaign["campaign_id"],
        "status": "DEVELOPMENT_SURVIVORS_REQUIRE_HUMAN_VALIDATION_APPROVAL" if survivor_count else "NO_DEVELOPMENT_SURVIVORS",
        "development_window": f"{_iso(start)}/{_iso(development_end)}",
        "development_survivor_count": survivor_count,
        "primary_hypothesis_count": len(MECHANISMS),
        "hypotheses": summaries,
        "events": events,
        "validation_rows_inspected": 0,
        "dated_confirmation_rows_inspected": 0,
        "automatic_validation_access_granted": False,
        "automatic_downstream_export": False,
        "paper_or_live_authority": False,
        "next_gate": "HUMAN_REVIEW_BEFORE_SEALED_VALIDATION" if survivor_count else "ARCHIVE_WITHOUT_RETUNING",
    }
