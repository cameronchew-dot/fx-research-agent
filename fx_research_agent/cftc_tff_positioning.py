from __future__ import annotations

import csv
import gzip
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .market_data import validate_manifest
from .motif_evaluation import _holm_adjust, _sign_flip_p_value, instrument_pip_size


RESULT_SCHEMA = "FX_CFTC_TFF_CROWDING_REVERSAL_DEVELOPMENT_RESULT_V1"


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value[:10]).replace(tzinfo=timezone.utc)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_reports(path: Path) -> dict[str, list[dict[str, Any]]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        source = list(csv.DictReader(handle))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in source:
        instrument = str(row["instrument"])
        report_date = str(row["report_date"])
        key = (instrument, report_date)
        if key in seen:
            raise ValueError(f"duplicate CFTC report: {key}")
        seen.add(key)
        share = float(row["leveraged_money_net_share"])
        if not math.isfinite(share) or abs(share) > 1:
            raise ValueError(f"invalid CFTC net share: {key}")
        grouped[instrument].append(
            {**row, "report_time": _parse_date(report_date), "net_share": share}
        )
    for rows in grouped.values():
        rows.sort(key=lambda item: item["report_time"])
    return dict(grouped)


def load_daily_candles(inbox_dir: Path, manifest_ids: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for instrument, manifest_id in manifest_ids.items():
        manifest_path = inbox_dir / f"{manifest_id}.manifest.json"
        validated = validate_manifest(manifest_path)
        if validated.get("instrument") != instrument:
            raise ValueError(f"daily candle manifest instrument mismatch: {manifest_id}")
        payload_path = inbox_dir / str(validated["payload_path"])
        with gzip.open(payload_path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("schema") != "FX_HISTORICAL_MARKET_DATA_PAYLOAD_V1":
            raise ValueError("CFTC research requires a sealed historical candle payload")
        quality = payload.get("quality") or {}
        if quality.get("future_outcomes_exported") is not False or quality.get("strategy_labels_exported") is not False:
            raise ValueError("historical candle payload does not prove label/outcome exclusion")
        candles = []
        seen: set[str] = set()
        for row in payload.get("completed_candles") or []:
            if row.get("instrument") != instrument or row.get("granularity") != "D":
                continue
            candle_time = str(row["candle_time_utc"])
            if candle_time in seen:
                raise ValueError(f"duplicate daily candle: {instrument}:{candle_time}")
            seen.add(candle_time)
            candles.append({**row, "time": _parse_utc(candle_time)})
        candles.sort(key=lambda item: item["time"])
        if len(candles) < 500:
            raise ValueError(f"insufficient daily candle history: {instrument}")
        grouped[instrument] = candles
    return grouped


def build_extreme_episodes(
    reports: list[dict[str, Any]],
    *,
    lookback: int,
    minimum_history: int,
    extreme_z: float,
    rearm_z: float,
    development_end: datetime,
) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    armed = True
    active_tail = 0
    for index, row in enumerate(reports):
        prior = [item["net_share"] for item in reports[max(0, index - lookback):index]]
        if len(prior) < minimum_history:
            continue
        mean = statistics.fmean(prior)
        std = statistics.pstdev(prior)
        if std <= 1e-12:
            continue
        z_score = (row["net_share"] - mean) / std
        tail = 1 if z_score >= extreme_z else -1 if z_score <= -extreme_z else 0
        if abs(z_score) < rearm_z:
            armed = True
            active_tail = 0
            continue
        if row["report_time"] >= development_end:
            continue
        if tail and (armed or tail != active_tail):
            episodes.append({**row, "z_score": z_score, "tail": tail})
            armed = False
            active_tail = tail
    return episodes


def _first_candle_after(candles: list[dict[str, Any]], timestamp: datetime) -> int | None:
    low, high = 0, len(candles)
    while low < high:
        middle = (low + high) // 2
        if candles[middle]["time"] <= timestamp:
            low = middle + 1
        else:
            high = middle
    return low if low < len(candles) else None


def _atr(candles: list[dict[str, Any]], entry_index: int, period: int) -> float | None:
    if entry_index < period + 1:
        return None
    ranges = []
    for index in range(entry_index - period, entry_index):
        row = candles[index]
        previous_close = float(candles[index - 1]["close"])
        high, low = float(row["high"]), float(row["low"])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    value = statistics.fmean(ranges)
    return value if math.isfinite(value) and value > 0 else None


def _outcome(
    candles: list[dict[str, Any]],
    entry_index: int,
    direction: str,
    *,
    atr_period: int,
    stop_atr: float,
    target_atr: float,
    horizon: int,
    cost_pips: float,
    pip_size: float,
    development_end: datetime,
) -> dict[str, Any] | None:
    final_index = entry_index + horizon - 1
    if final_index >= len(candles) or candles[final_index]["time"] >= development_end:
        return None
    atr = _atr(candles, entry_index, atr_period)
    if atr is None:
        return None
    entry = float(candles[entry_index]["open"])
    risk = stop_atr * atr
    sign = 1.0 if direction == "LONG" else -1.0
    stop = entry - sign * risk
    target = entry + sign * target_atr * atr
    exit_price = float(candles[final_index]["close"])
    exit_reason = "HORIZON"
    exit_index = final_index
    gross_r: float | None = None
    mfe, mae = -math.inf, math.inf
    for index in range(entry_index, final_index + 1):
        row = candles[index]
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
            exit_price, exit_reason, gross_r, exit_index = target, "TARGET_GAP_CONSERVATIVE", target_atr / stop_atr, index
            break
        if stop_touched:
            exit_price, exit_reason, gross_r, exit_index = stop, "STOP", -1.0, index
            break
        if target_touched:
            exit_price, exit_reason, gross_r, exit_index = target, "TARGET", target_atr / stop_atr, index
            break
    if gross_r is None:
        gross_r = sign * (exit_price - entry) / risk
    cost_r = cost_pips / (risk / pip_size)
    return {
        "entry_time_utc": candles[entry_index]["candle_time_utc"],
        "exit_time_utc": candles[exit_index]["candle_end_time_utc"],
        "entry": round(entry, 8),
        "stop": round(stop, 8),
        "target": round(target, 8),
        "exit_price": round(exit_price, 8),
        "exit_reason": exit_reason,
        "stop_distance_pips": round(risk / pip_size, 6),
        "gross_r": round(gross_r, 8),
        "cost_r": round(cost_r, 8),
        "net_r": round(gross_r - cost_r, 8),
        "mfe_r": round(mfe, 8),
        "mae_r": round(mae, 8),
        "final_index": final_index,
    }


def _direction(instrument: str, tail: int) -> str:
    sign = tail if instrument == "USD_JPY" else -tail
    return "LONG" if sign > 0 else "SHORT"


def _metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = np.asarray([float(row[key]) for row in rows], dtype=float)
    years: dict[str, list[float]] = defaultdict(list)
    for row, value in zip(rows, values):
        years[str(row["report_date"])[:4]].append(float(value))
    year_means = [float(np.mean(items)) for items in years.values()]
    positives = np.sort(values[values > 0])[::-1]
    top_count = max(1, int(math.ceil(0.05 * len(values)))) if len(values) else 0
    top_fraction = float(positives[:top_count].sum() / positives.sum()) if positives.sum() > 0 else 1.0
    return {
        "event_count": int(len(values)),
        "calendar_year_count": len(years),
        "average_net_r": round(float(values.mean()), 8) if len(values) else None,
        "median_net_r": round(float(np.median(values)), 8) if len(values) else None,
        "positive_net_r_rate": round(float(np.mean(values > 0)), 8) if len(values) else None,
        "positive_year_rate": round(float(np.mean(np.asarray(year_means) > 0)), 8) if year_means else None,
        "worst_year_average_net_r": round(min(year_means), 8) if year_means else None,
        "top_five_percent_positive_r_contribution_fraction": round(top_fraction, 8),
        "total_net_r": round(float(values.sum()), 8) if len(values) else 0.0,
    }


def _gate_blocks(summary: dict[str, Any], gates: dict[str, Any]) -> list[str]:
    checks = (
        (summary["event_count"] >= gates["minimum_independent_events_per_instrument"], "INSUFFICIENT_EVENTS"),
        (summary["average_net_r"] is not None and summary["average_net_r"] >= gates["minimum_average_net_r"], "AVERAGE_NET_R_BELOW_MIN"),
        (summary["median_net_r"] is not None and summary["median_net_r"] > gates["minimum_median_net_r_exclusive"], "MEDIAN_NET_R_NOT_POSITIVE"),
        (summary["positive_net_r_rate"] is not None and summary["positive_net_r_rate"] >= gates["minimum_positive_net_r_rate"], "POSITIVE_RATE_BELOW_MIN"),
        (summary["positive_year_rate"] is not None and summary["positive_year_rate"] >= gates["minimum_positive_year_rate"], "POSITIVE_YEAR_RATE_BELOW_MIN"),
        (summary["worst_year_average_net_r"] is not None and summary["worst_year_average_net_r"] >= gates["minimum_worst_year_average_net_r"], "WORST_YEAR_BELOW_MIN"),
        (summary["top_five_percent_positive_r_contribution_fraction"] <= gates["maximum_top_five_percent_positive_r_contribution_fraction"], "OUTLIER_DEPENDENCE_ABOVE_MAX"),
        (summary["edge_over_opposite_control"] >= gates["minimum_average_net_r_edge_over_each_control"], "OPPOSITE_CONTROL_EDGE_BELOW_MIN"),
        (summary["edge_over_shifted_control"] >= gates["minimum_average_net_r_edge_over_each_control"], "SHIFTED_CONTROL_EDGE_BELOW_MIN"),
        (summary["holm_adjusted_p_value"] <= gates["holm_adjusted_p_value_maximum"], "HOLM_SIGNIFICANCE_NOT_CLEAR"),
    )
    return [label for passed, label in checks if not passed]


def evaluate_development(
    reports_path: Path,
    inbox_dir: Path,
    campaign: dict[str, Any],
    *,
    draws: int = 20000,
    seed: int = 20261029,
) -> dict[str, Any]:
    reports = load_reports(reports_path)
    candles = load_daily_candles(inbox_dir, campaign["source_manifest_ids"])
    spec = campaign["exact_specification"]
    independence = campaign["independence_unit"]
    development_end = datetime(2017, 1, 1, tzinfo=timezone.utc)
    rows_by_instrument: dict[str, list[dict[str, Any]]] = {}
    summaries = []
    raw_p_values = []
    for instrument in campaign["instruments"]:
        episodes = build_extreme_episodes(
            reports[instrument],
            lookback=int(spec["z_score_lookback_prior_reports"]),
            minimum_history=int(spec["minimum_prior_reports"]),
            extreme_z=float(independence["extreme_entry_absolute_z"]),
            rearm_z=float(independence["rearm_below_absolute_z"]),
            development_end=development_end,
        )
        instrument_rows = []
        last_primary_final_index = -1
        for episode in episodes:
            available = episode["report_time"] + timedelta(days=int(spec["availability_lag_calendar_days"]))
            entry_index = _first_candle_after(candles[instrument], available)
            shifted_index = _first_candle_after(candles[instrument], available + timedelta(days=182))
            if entry_index is None or shifted_index is None or entry_index <= last_primary_final_index:
                continue
            direction = _direction(instrument, int(episode["tail"]))
            common = {
                "atr_period": int(spec["atr_period_prior_completed_daily_bars"]),
                "stop_atr": float(spec["stop_atr_multiple"]),
                "target_atr": float(spec["target_atr_multiple"]),
                "horizon": int(spec["maximum_horizon_daily_bars"]),
                "cost_pips": float(spec["fixed_round_trip_cost_pips"]),
                "pip_size": instrument_pip_size(instrument),
                "development_end": development_end,
            }
            primary = _outcome(candles[instrument], entry_index, direction, **common)
            opposite = _outcome(candles[instrument], entry_index, "SHORT" if direction == "LONG" else "LONG", **common)
            shifted = _outcome(candles[instrument], shifted_index, direction, **common)
            if primary is None or opposite is None or shifted is None:
                continue
            last_primary_final_index = int(primary["final_index"])
            for outcome in (primary, opposite, shifted):
                outcome.pop("final_index", None)
            instrument_rows.append(
                {
                    "report_id": episode["report_id"],
                    "report_date": episode["report_date"],
                    "available_after_utc": available.isoformat().replace("+00:00", "Z"),
                    "instrument": instrument,
                    "z_score": round(float(episode["z_score"]), 8),
                    "direction": direction,
                    "primary_net_r": primary["net_r"],
                    "opposite_net_r": opposite["net_r"],
                    "shifted_net_r": shifted["net_r"],
                    "primary": primary,
                    "opposite_direction_control": opposite,
                    "shifted_event_control": shifted,
                }
            )
        rows_by_instrument[instrument] = instrument_rows
        primary = _metrics(instrument_rows, "primary_net_r")
        opposite = _metrics(instrument_rows, "opposite_net_r")
        shifted = _metrics(instrument_rows, "shifted_net_r")
        primary["edge_over_opposite_control"] = round((primary["average_net_r"] or 0) - (opposite["average_net_r"] or 0), 8)
        primary["edge_over_shifted_control"] = round((primary["average_net_r"] or 0) - (shifted["average_net_r"] or 0), 8)
        differences = np.asarray(
            [row["primary_net_r"] - max(row["opposite_net_r"], row["shifted_net_r"]) for row in instrument_rows],
            dtype=float,
        )
        p_value = _sign_flip_p_value(differences, draws=draws, seed=seed + len(summaries)) if len(differences) else 1.0
        raw_p_values.append(p_value)
        summaries.append(
            {
                "instrument": instrument,
                "primary": primary,
                "opposite_direction_control": opposite,
                "shifted_event_control": shifted,
                "paired_edge_over_stronger_control_average_r": round(float(differences.mean()), 8) if len(differences) else None,
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
        "development_window_end_exclusive": development_end.isoformat().replace("+00:00", "Z"),
        "instrument_hypothesis_count": len(summaries),
        "development_survivor_count": survivor_count,
        "hypotheses": summaries,
        "events": rows_by_instrument,
        "validation_rows_inspected": 0,
        "holdout_rows_inspected": 0,
        "automatic_validation_access_granted": False,
        "automatic_downstream_export": False,
        "paper_or_live_authority": False,
        "next_gate": "HUMAN_REVIEW_BEFORE_SEALED_VALIDATION" if survivor_count else "ARCHIVE_WITHOUT_RETUNING",
    }
