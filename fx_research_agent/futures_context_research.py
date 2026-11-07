from __future__ import annotations

import bisect
import gzip
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from .market_data import validate_manifest
from .motif_evaluation import _holm_adjust, _sign_flip_p_value, instrument_pip_size


RESULT_SCHEMA = "FX_MULTIPAIR_CME_FUTURES_CONTEXT_DEVELOPMENT_RESULT_V1"
TREATMENTS = (
    "INTRADAY_VOLUME_CONFIRMATION",
    "OI_AND_SETTLEMENT_CONFIRMATION",
    "ALL_CONTEXT_CONFLUENCE",
)
PAIR_TO_PRODUCT = {"EUR_USD": "6E", "USD_JPY": "6J", "AUD_USD": "6A"}


def _utc(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def load_spot_m15(
    inbox_dir: Path,
    manifest_id: str,
    instrument: str,
    *,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    manifest = validate_manifest(inbox_dir / f"{manifest_id}.manifest.json")
    if manifest.get("instrument") != instrument:
        raise ValueError(f"spot manifest instrument mismatch: {manifest_id}")
    with gzip.open(inbox_dir / str(manifest["payload_path"]), "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema") != "FX_HISTORICAL_MARKET_DATA_PAYLOAD_V1":
        raise ValueError("futures-context research requires sealed historical candles")
    quality = payload.get("quality") or {}
    if quality.get("future_outcomes_exported") is not False or quality.get("strategy_labels_exported") is not False:
        raise ValueError("spot payload does not prove outcome and strategy-label exclusion")
    rows = [
        row
        for row in payload.get("completed_candles") or []
        if row.get("instrument") == instrument and row.get("granularity") == "M15"
    ]
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"no M15 candles in {manifest_id}")
    frame["time"] = pd.to_datetime(frame["candle_time_utc"], utc=True)
    frame["end_time"] = pd.to_datetime(frame["candle_end_time_utc"], utc=True)
    frame = frame[(frame["time"] >= pd.Timestamp(start)) & (frame["end_time"] < pd.Timestamp(end))].copy()
    frame.sort_values("time", inplace=True)
    if frame["time"].duplicated().any():
        raise ValueError(f"duplicate M15 candles: {instrument}")
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column].astype(float)
    return frame.reset_index(drop=True)


def load_futures_m15(
    path: Path,
    *,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    dataset = ds.dataset(path)
    predicate = (ds.field("event_time_utc") >= start) & (ds.field("event_time_utc") < end)
    table = dataset.to_table(
        filter=predicate,
        columns=["event_time_utc", "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "volume"],
    )
    frame = table.to_pandas()
    frame["event_time_utc"] = pd.to_datetime(frame["event_time_utc"], utc=True)
    frame.sort_values("event_time_utc", inplace=True)
    frame.set_index("event_time_utc", inplace=True)
    bars = frame.resample("15min", label="left", closed="left").agg(
        open=("adjusted_open", "first"),
        high=("adjusted_high", "max"),
        low=("adjusted_low", "min"),
        close=("adjusted_close", "last"),
        volume=("volume", "sum"),
        source_minutes=("volume", "count"),
    )
    bars = bars[bars["source_minutes"] > 0].copy()
    bars["end_time"] = bars.index + pd.Timedelta(minutes=15)
    local = bars.index.tz_convert("America/New_York")
    bars["local_slot"] = local.hour * 4 + local.minute // 15
    baseline = bars.groupby("local_slot", group_keys=False)["volume"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).median()
    )
    bars["volume_baseline"] = baseline
    bars["volume_ratio"] = bars["volume"] / baseline.replace(0, np.nan)
    bars["return"] = bars["close"] / bars["open"] - 1.0
    return bars.reset_index(drop=True).set_index("end_time", drop=False)


def load_official_statistics(path: Path, *, end: datetime) -> pd.DataFrame:
    dataset = ds.dataset(path)
    predicate = (
        (ds.field("available_at_utc") < end)
        & (ds.field("is_selected_contract") == True)
        & ((ds.field("normalized_stat_type") == 3) | (ds.field("normalized_stat_type") == 9))
    )
    table = dataset.to_table(
        filter=predicate,
        columns=[
            "available_at_utc",
            "reference_time_utc",
            "normalized_stat_name",
            "normalized_price",
            "quantity",
        ],
    )
    frame = table.to_pandas()
    frame["available_at_utc"] = pd.to_datetime(frame["available_at_utc"], utc=True)
    frame["reference_time_utc"] = pd.to_datetime(frame["reference_time_utc"], utc=True)
    return frame.sort_values("available_at_utc").reset_index(drop=True)


def statistic_changes_before(
    statistics_frame: pd.DataFrame,
    decisions: list[pd.Timestamp],
    statistic_name: str,
) -> dict[pd.Timestamp, dict[str, Any]]:
    rows = statistics_frame[statistics_frame["normalized_stat_name"] == statistic_name].copy()
    value_column = "quantity" if statistic_name == "OPEN_INTEREST" else "normalized_price"
    rows = rows[rows[value_column].notna()].sort_values("available_at_utc")
    source = rows.to_dict("records")
    ordered_references: list[pd.Timestamp] = []
    latest_by_reference: dict[pd.Timestamp, tuple[float, pd.Timestamp]] = {}
    output: dict[pd.Timestamp, dict[str, Any]] = {}
    source_index = 0
    for decision in sorted(set(decisions)):
        while source_index < len(source) and pd.Timestamp(source[source_index]["available_at_utc"]) < decision:
            row = source[source_index]
            reference = pd.Timestamp(row["reference_time_utc"])
            if reference not in latest_by_reference:
                bisect.insort(ordered_references, reference)
            latest_by_reference[reference] = (float(row[value_column]), pd.Timestamp(row["available_at_utc"]))
            source_index += 1
        if len(ordered_references) < 2:
            continue
        current_reference, previous_reference = ordered_references[-1], ordered_references[-2]
        current, available_at = latest_by_reference[current_reference]
        previous, _ = latest_by_reference[previous_reference]
        output[decision] = {
            "current": current,
            "previous": previous,
            "change": current - previous,
            "current_reference_time_utc": _iso(current_reference),
            "previous_reference_time_utc": _iso(previous_reference),
            "available_at_utc": _iso(available_at),
        }
    return output


def _trading_day(times: pd.Series) -> pd.Series:
    local = times.dt.tz_convert("America/New_York")
    return (local + pd.Timedelta(hours=7)).dt.date.astype(str)


def build_spot_events(
    frame: pd.DataFrame,
    instrument: str,
    specification: dict[str, Any],
) -> list[dict[str, Any]]:
    pip_size = instrument_pip_size(instrument)
    target_r = float(specification["target_r"])
    horizon = int(specification["maximum_horizon_m15_bars"])
    cost_pips = float(specification["fixed_round_trip_cost_pips"][instrument])
    frame = frame.copy()
    frame["trading_day"] = _trading_day(frame["time"])
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr14"] = true_range.shift(1).rolling(14, min_periods=14).mean()
    daily = frame.groupby("trading_day", sort=True).agg(day_high=("high", "max"), day_low=("low", "min"))
    daily["prior_high"] = daily["day_high"].shift(1)
    daily["prior_low"] = daily["day_low"].shift(1)
    frame = frame.join(daily[["prior_high", "prior_low"]], on="trading_day")

    candidates: list[dict[str, Any]] = []
    for trading_day, day in frame.groupby("trading_day", sort=True):
        day = day.sort_index()
        if day["prior_high"].isna().all() or day["prior_low"].isna().all():
            continue
        states: dict[str, dict[str, Any]] = {
            "LONG": {"breakout_index": None, "emitted": False},
            "SHORT": {"breakout_index": None, "emitted": False},
        }
        for index, row in day.iterrows():
            atr = float(row["atr14"]) if pd.notna(row["atr14"]) else math.nan
            if not math.isfinite(atr) or atr <= 0:
                continue
            breakout_pad = max(1.0 * pip_size, 0.05 * atr)
            touch_distance = max(1.5 * pip_size, 0.10 * atr)
            hold_distance = 0.5 * pip_size
            levels = {"LONG": float(row["prior_high"]), "SHORT": float(row["prior_low"])}
            for direction in ("LONG", "SHORT"):
                state = states[direction]
                if state["emitted"]:
                    continue
                level = levels[direction]
                breakout = (
                    float(row["close"]) >= level + breakout_pad
                    if direction == "LONG"
                    else float(row["close"]) <= level - breakout_pad
                )
                if state["breakout_index"] is None:
                    if breakout:
                        state["breakout_index"] = int(index)
                    continue
                bars_since = int(index) - int(state["breakout_index"])
                if bars_since > 8:
                    state["breakout_index"] = int(index) if breakout else None
                    continue
                if bars_since <= 0:
                    continue
                retest = (
                    float(row["low"]) <= level + touch_distance and float(row["close"]) >= level + hold_distance
                    if direction == "LONG"
                    else float(row["high"]) >= level - touch_distance and float(row["close"]) <= level - hold_distance
                )
                if not retest or int(index) + horizon >= len(frame):
                    continue
                entry_index = int(index) + 1
                entry = float(frame.at[entry_index, "open"])
                buffer = max(1.0 * pip_size, 0.05 * atr)
                raw_stop = float(row["low"]) - buffer if direction == "LONG" else float(row["high"]) + buffer
                minimum_risk = 4.0 * pip_size
                risk = max(abs(entry - raw_stop), minimum_risk)
                sign = 1.0 if direction == "LONG" else -1.0
                stop = entry - sign * risk
                target = entry + sign * target_r * risk
                outcome = _outcome(
                    frame,
                    entry_index,
                    direction,
                    stop=stop,
                    target=target,
                    risk=risk,
                    horizon=horizon,
                    cost_pips=cost_pips,
                    pip_size=pip_size,
                )
                candidates.append(
                    {
                        "instrument": instrument,
                        "trading_day": trading_day,
                        "direction": direction,
                        "level_type": "PRIOR_DAY_HIGH" if direction == "LONG" else "PRIOR_DAY_LOW",
                        "level": round(level, 8),
                        "breakout_index": int(state["breakout_index"]),
                        "decision_index": int(index),
                        "decision_time": pd.Timestamp(row["end_time"]),
                        "atr14": atr,
                        **outcome,
                    }
                )
                state["emitted"] = True

    candidates.sort(key=lambda item: (item["decision_time"], item["instrument"], item["direction"]))
    independent: list[dict[str, Any]] = []
    last_final_index = -1
    for row in candidates:
        if int(row["entry_index"]) <= last_final_index:
            continue
        last_final_index = int(row["final_index"])
        independent.append(row)
    return independent


def _outcome(
    frame: pd.DataFrame,
    entry_index: int,
    direction: str,
    *,
    stop: float,
    target: float,
    risk: float,
    horizon: int,
    cost_pips: float,
    pip_size: float,
) -> dict[str, Any]:
    final_index = entry_index + horizon - 1
    entry = float(frame.at[entry_index, "open"])
    sign = 1.0 if direction == "LONG" else -1.0
    exit_index = final_index
    exit_price = float(frame.at[final_index, "close"])
    exit_reason = "HORIZON"
    gross_r: float | None = None
    mfe, mae = -math.inf, math.inf
    for index in range(entry_index, final_index + 1):
        row = frame.loc[index]
        open_, high, low = float(row["open"]), float(row["high"]), float(row["low"])
        favorable = (high - entry) / risk if direction == "LONG" else (entry - low) / risk
        adverse = (low - entry) / risk if direction == "LONG" else (entry - high) / risk
        mfe, mae = max(mfe, favorable), min(mae, adverse)
        adverse_gap = open_ <= stop if direction == "LONG" else open_ >= stop
        favorable_gap = open_ >= target if direction == "LONG" else open_ <= target
        stop_touched = low <= stop if direction == "LONG" else high >= stop
        target_touched = high >= target if direction == "LONG" else low <= target
        if adverse_gap:
            exit_price, exit_reason, gross_r, exit_index = open_, "STOP_GAP", sign * (open_ - entry) / risk, index
            break
        if favorable_gap:
            exit_price, exit_reason, gross_r, exit_index = target, "TARGET_GAP_CONSERVATIVE", (target - entry) * sign / risk, index
            break
        if stop_touched:
            exit_price, exit_reason, gross_r, exit_index = stop, "STOP", -1.0, index
            break
        if target_touched:
            exit_price, exit_reason, gross_r, exit_index = target, "TARGET", (target - entry) * sign / risk, index
            break
    if gross_r is None:
        gross_r = sign * (exit_price - entry) / risk
    cost_r = cost_pips / (risk / pip_size)
    return {
        "entry_index": entry_index,
        "final_index": final_index,
        "entry_time_utc": _iso(frame.at[entry_index, "time"]),
        "exit_time_utc": _iso(frame.at[exit_index, "end_time"]),
        "entry": round(entry, 8),
        "stop": round(stop, 8),
        "target": round(target, 8),
        "exit_price": round(exit_price, 8),
        "exit_reason": exit_reason,
        "stop_distance_pips": round(risk / pip_size, 6),
        "gross_r": round(float(gross_r), 8),
        "cost_r": round(float(cost_r), 8),
        "net_r": round(float(gross_r - cost_r), 8),
        "mfe_r": round(float(mfe), 8),
        "mae_r": round(float(mae), 8),
    }


def attach_futures_context(
    events: list[dict[str, Any]],
    futures_bars: pd.DataFrame,
    statistics_frame: pd.DataFrame,
) -> list[dict[str, Any]]:
    decisions = [pd.Timestamp(row["decision_time"]) for row in events]
    open_interest = statistic_changes_before(statistics_frame, decisions, "OPEN_INTEREST")
    settlement = statistic_changes_before(statistics_frame, decisions, "SETTLEMENT_PRICE")
    output = []
    for row in events:
        decision = pd.Timestamp(row["decision_time"])
        futures = futures_bars.loc[decision] if decision in futures_bars.index else None
        if isinstance(futures, pd.DataFrame):
            futures = futures.iloc[-1]
        oi = open_interest.get(decision)
        settle = settlement.get(decision)
        sign = 1.0 if row["direction"] == "LONG" else -1.0
        futures_return = float(futures["return"]) if futures is not None else math.nan
        volume_ratio = float(futures["volume_ratio"]) if futures is not None else math.nan
        volume_available = math.isfinite(futures_return) and math.isfinite(volume_ratio)
        volume_high = volume_available and volume_ratio >= 1.25
        volume_aligned = volume_high and sign * futures_return > 0
        volume_opposed = volume_high and sign * futures_return < 0
        oi_increase = oi is not None and float(oi["change"]) > 0
        settlement_change = float(settle["change"]) if settle is not None else math.nan
        settlement_aligned = math.isfinite(settlement_change) and sign * settlement_change > 0
        settlement_opposed = math.isfinite(settlement_change) and sign * settlement_change < 0
        oi_settlement_aligned = oi_increase and settlement_aligned
        oi_settlement_opposed = oi_increase and settlement_opposed
        enriched = {
            **row,
            "decision_time_utc": _iso(decision),
            "futures_return_15m": round(futures_return, 10) if math.isfinite(futures_return) else None,
            "futures_volume_ratio": round(volume_ratio, 8) if math.isfinite(volume_ratio) else None,
            "open_interest_change": round(float(oi["change"]), 4) if oi else None,
            "settlement_change": round(settlement_change, 10) if math.isfinite(settlement_change) else None,
            "open_interest_available_at_utc": oi["available_at_utc"] if oi else None,
            "settlement_available_at_utc": settle["available_at_utc"] if settle else None,
            "treatment_membership": {
                "INTRADAY_VOLUME_CONFIRMATION": bool(volume_aligned),
                "OI_AND_SETTLEMENT_CONFIRMATION": bool(oi_settlement_aligned),
                "ALL_CONTEXT_CONFLUENCE": bool(volume_aligned and oi_settlement_aligned),
            },
            "opposite_context_membership": {
                "INTRADAY_VOLUME_CONFIRMATION": bool(volume_opposed),
                "OI_AND_SETTLEMENT_CONFIRMATION": bool(oi_settlement_opposed),
                "ALL_CONTEXT_CONFLUENCE": bool(volume_opposed and oi_settlement_opposed),
            },
        }
        enriched.pop("decision_time", None)
        enriched.pop("entry_index", None)
        enriched.pop("final_index", None)
        enriched.pop("breakout_index", None)
        enriched.pop("decision_index", None)
        output.append(enriched)
    return output


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = np.asarray([float(row["net_r"]) for row in rows], dtype=float)
    months: dict[str, list[float]] = defaultdict(list)
    for row, value in zip(rows, values):
        months[str(row["decision_time_utc"])[:7]].append(float(value))
    month_means = [float(np.mean(month)) for month in months.values()]
    positives = np.sort(values[values > 0])[::-1]
    top_count = max(1, int(math.ceil(0.05 * len(values)))) if len(values) else 0
    top_fraction = float(positives[:top_count].sum() / positives.sum()) if positives.sum() > 0 else 1.0
    equity = np.cumsum(values) if len(values) else np.asarray([], dtype=float)
    running_high = np.maximum.accumulate(np.concatenate(([0.0], equity)))
    drawdowns = np.concatenate(([0.0], equity)) - running_high
    return {
        "event_count": int(len(values)),
        "calendar_month_count": len(months),
        "average_net_r": round(float(values.mean()), 8) if len(values) else None,
        "median_net_r": round(float(np.median(values)), 8) if len(values) else None,
        "positive_net_r_rate": round(float(np.mean(values > 0)), 8) if len(values) else None,
        "positive_month_rate": round(float(np.mean(np.asarray(month_means) > 0)), 8) if month_means else None,
        "worst_month_average_net_r": round(min(month_means), 8) if month_means else None,
        "maximum_drawdown_r": round(float(drawdowns.min()), 8) if len(drawdowns) else 0.0,
        "average_mfe_r": round(statistics.fmean(float(row["mfe_r"]) for row in rows), 8) if rows else None,
        "average_mae_r": round(statistics.fmean(float(row["mae_r"]) for row in rows), 8) if rows else None,
        "top_five_percent_positive_r_contribution_fraction": round(top_fraction, 8),
        "total_net_r": round(float(values.sum()), 8) if len(values) else 0.0,
    }


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
        (summary["edge_over_unfiltered_r"] >= gates["minimum_average_net_r_edge_over_unfiltered"], "UNFILTERED_EDGE_BELOW_MIN"),
        (summary["edge_over_opposite_context_r"] >= gates["minimum_average_net_r_edge_over_opposite_context"], "OPPOSITE_CONTEXT_EDGE_BELOW_MIN"),
        (summary["holm_adjusted_p_value"] <= gates["holm_adjusted_p_value_maximum"], "HOLM_SIGNIFICANCE_NOT_CLEAR"),
    )
    return [label for passed, label in checks if not passed]


def evaluate_development(
    root: Path,
    campaign: dict[str, Any],
    *,
    draws: int = 20000,
    seed: int = 20261107,
) -> dict[str, Any]:
    start = _utc(campaign["population"]["common_history_start_inclusive"])
    development_end = _utc(campaign["population"]["development_decision_time_end_exclusive"])
    all_events: dict[str, list[dict[str, Any]]] = {}
    pooled: list[dict[str, Any]] = []
    for instrument in campaign["instruments"]:
        product = PAIR_TO_PRODUCT[instrument]
        build_id = campaign["futures_build_ids"][product]
        derived = root / "data" / "derived" / "databento_continuous" / product / build_id
        spot = load_spot_m15(
            root / "data" / "inbox",
            campaign["source_manifest_ids"][instrument],
            instrument,
            start=start,
            end=development_end,
        )
        spot_events = build_spot_events(spot, instrument, campaign["exact_specification"]["spot_setup"])
        futures = load_futures_m15(
            derived / "continuous_bars_1m.parquet",
            start=start - timedelta(days=40),
            end=development_end,
        )
        official = load_official_statistics(derived / "official_statistics.parquet", end=development_end)
        events = attach_futures_context(spot_events, futures, official)
        all_events[instrument] = events
        pooled.extend(events)
    pooled.sort(key=lambda row: (row["decision_time_utc"], row["instrument"], row["direction"]))
    unfiltered = _metrics(pooled)
    summaries = []
    raw_p_values = []
    for treatment_index, treatment in enumerate(TREATMENTS):
        selected = [row for row in pooled if row["treatment_membership"][treatment]]
        opposite = [row for row in pooled if row["opposite_context_membership"][treatment]]
        summary = _metrics(selected)
        opposite_summary = _metrics(opposite)
        unfiltered_average = float(unfiltered["average_net_r"] or 0.0)
        opposite_average = float(opposite_summary["average_net_r"] or 0.0)
        summary["edge_over_unfiltered_r"] = round(float(summary["average_net_r"] or 0.0) - unfiltered_average, 8)
        summary["edge_over_opposite_context_r"] = round(float(summary["average_net_r"] or 0.0) - opposite_average, 8)
        benchmark = max(unfiltered_average, opposite_average)
        differences = np.asarray([float(row["net_r"]) - benchmark for row in selected], dtype=float)
        p_value = _sign_flip_p_value(differences, draws=draws, seed=seed + treatment_index) if len(differences) else 1.0
        raw_p_values.append(p_value)
        pair_breakdown = {
            instrument: _metrics([row for row in selected if row["instrument"] == instrument])
            for instrument in campaign["instruments"]
        }
        summaries.append(
            {
                "treatment": treatment,
                "primary": summary,
                "opposite_context_control": opposite_summary,
                "unfiltered_control_average_net_r": unfiltered["average_net_r"],
                "pair_breakdown_descriptive_only": pair_breakdown,
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
        "unfiltered_spot_setup": unfiltered,
        "primary_hypothesis_count": len(TREATMENTS),
        "hypotheses": summaries,
        "events": all_events,
        "validation_rows_inspected": 0,
        "dated_confirmation_rows_inspected": 0,
        "automatic_validation_access_granted": False,
        "automatic_downstream_export": False,
        "paper_or_live_authority": False,
        "next_gate": "HUMAN_REVIEW_BEFORE_SEALED_VALIDATION" if survivor_count else "ARCHIVE_WITHOUT_RETUNING",
    }
