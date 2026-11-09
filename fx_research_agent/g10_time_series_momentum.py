from __future__ import annotations

import csv
import gzip
import hashlib
import math
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any


INSTRUMENTS = (
    "EUR_USD",
    "GBP_USD",
    "AUD_USD",
    "NZD_USD",
    "USD_JPY",
    "USD_CHF",
    "USD_CAD",
)
LOOKBACK_DAYS = (21, 63, 126)
VOLATILITY_DAYS = 20
PAIR_WEIGHT_CAP = 0.25
NET_USD_FACTOR_CAP = 0.50


def load_daily_spot(path: Path) -> tuple[list[str], dict[str, dict[str, float]]]:
    panel: dict[str, dict[str, float]] = defaultdict(dict)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            instrument = row["instrument"]
            if instrument in INSTRUMENTS:
                value = float(row["normalized_usd_per_foreign_currency"])
                if not math.isfinite(value) or value <= 0:
                    raise ValueError(f"invalid daily spot value: {row['date']}:{instrument}")
                panel[row["date"]][instrument] = value
    complete = {
        day: prices
        for day, prices in panel.items()
        if all(instrument in prices for instrument in INSTRUMENTS)
    }
    return sorted(complete), complete


def _weekly_decision_dates(days: list[str]) -> list[str]:
    by_week: dict[tuple[int, int], list[str]] = defaultdict(list)
    for day in days:
        parsed = date.fromisoformat(day)
        iso_year, iso_week, _ = parsed.isocalendar()
        by_week[(iso_year, iso_week)].append(day)
    return [max(values) for _, values in sorted(by_week.items())]


def _daily_volatility(
    days: list[str],
    panel: dict[str, dict[str, float]],
    day_index: int,
    instrument: str,
) -> float | None:
    if day_index < VOLATILITY_DAYS:
        return None
    returns = [
        math.log(panel[days[index]][instrument] / panel[days[index - 1]][instrument])
        for index in range(day_index - VOLATILITY_DAYS + 1, day_index + 1)
    ]
    if len(returns) < 2:
        return None
    value = statistics.stdev(returns)
    return value if value > 0 else None


def _apply_caps(raw: dict[str, float]) -> dict[str, float]:
    total = sum(abs(value) for value in raw.values())
    if total <= 0:
        return {instrument: 0.0 for instrument in INSTRUMENTS}
    weights = {
        instrument: max(-PAIR_WEIGHT_CAP, min(PAIR_WEIGHT_CAP, raw.get(instrument, 0.0) / total))
        for instrument in INSTRUMENTS
    }
    net = sum(weights.values())
    if abs(net) <= NET_USD_FACTOR_CAP:
        return weights
    majority_sign = 1.0 if net > 0 else -1.0
    majority = sum(value for value in weights.values() if value * majority_sign > 0)
    minority = sum(value for value in weights.values() if value * majority_sign < 0)
    target_majority = majority_sign * NET_USD_FACTOR_CAP - minority
    scale = abs(target_majority / majority) if majority else 0.0
    return {
        instrument: value * scale if value * majority_sign > 0 else value
        for instrument, value in weights.items()
    }


def _primary_target(
    days: list[str],
    panel: dict[str, dict[str, float]],
    day_index: int,
) -> tuple[dict[str, float], dict[str, Any]] | None:
    if day_index < max(LOOKBACK_DAYS):
        return None
    raw: dict[str, float] = {}
    votes: dict[str, int] = {}
    returns: dict[str, list[float]] = {}
    volatilities: dict[str, float] = {}
    for instrument in INSTRUMENTS:
        current = panel[days[day_index]][instrument]
        horizon_returns = [
            math.log(current / panel[days[day_index - lookback]][instrument])
            for lookback in LOOKBACK_DAYS
        ]
        vote = sum(1 if value > 0 else -1 if value < 0 else 0 for value in horizon_returns)
        volatility = _daily_volatility(days, panel, day_index, instrument)
        returns[instrument] = horizon_returns
        votes[instrument] = vote
        if abs(vote) >= 2 and volatility:
            direction = 1.0 if vote > 0 else -1.0
            raw[instrument] = direction / volatility
            volatilities[instrument] = volatility
    return _apply_caps(raw), {
        "votes": votes,
        "lookback_log_returns": returns,
        "daily_volatility": volatilities,
    }


def _random_target(primary: dict[str, float], decision_day: str) -> dict[str, float]:
    raw = {}
    for instrument, weight in primary.items():
        if weight == 0:
            continue
        digest = hashlib.sha256(f"20261109:{decision_day}:{instrument}".encode()).digest()
        raw[instrument] = abs(weight) * (1.0 if digest[0] % 2 else -1.0)
    return _apply_caps(raw)


def _usd_factor_target(
    days: list[str],
    panel: dict[str, dict[str, float]],
    day_index: int,
) -> dict[str, float]:
    basket = statistics.fmean(
        math.log(panel[days[day_index]][instrument] / panel[days[day_index - 126]][instrument])
        for instrument in INSTRUMENTS
    )
    direction = 1.0 if basket > 0 else -1.0 if basket < 0 else 0.0
    raw = {}
    for instrument in INSTRUMENTS:
        volatility = _daily_volatility(days, panel, day_index, instrument)
        if volatility and direction:
            raw[instrument] = direction / volatility
    return _apply_caps(raw)


def target_series(
    days: list[str],
    panel: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    index_by_day = {day: index for index, day in enumerate(days)}
    rows: list[dict[str, Any]] = []
    prior_primary: dict[str, float] | None = None
    for decision_day in _weekly_decision_dates(days):
        day_index = index_by_day[decision_day]
        primary_result = _primary_target(days, panel, day_index)
        if primary_result is None or day_index + 1 >= len(days):
            continue
        primary, diagnostics = primary_result
        rows.append(
            {
                "decision_date": decision_day,
                "effective_date": days[day_index + 1],
                "PRIMARY": primary,
                "OPPOSITE": {instrument: -weight for instrument, weight in primary.items()},
                "STALE": prior_primary or {instrument: 0.0 for instrument in INSTRUMENTS},
                "RANDOM": _random_target(primary, decision_day),
                "USD_FACTOR": _usd_factor_target(days, panel, day_index),
                "diagnostics": diagnostics,
            }
        )
        prior_primary = primary
    return rows


def portfolio_rows(
    days: list[str],
    panel: dict[str, dict[str, float]],
    targets: list[dict[str, Any]],
    *,
    control: str = "PRIMARY",
    one_way_cost_bps: float = 5.0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous = {instrument: 0.0 for instrument in INSTRUMENTS}
    for current, following in zip(targets, targets[1:]):
        weights = current[control]
        entry_day = current["effective_date"]
        exit_day = following["effective_date"]
        gross = sum(
            weights[instrument]
            * math.log(panel[exit_day][instrument] / panel[entry_day][instrument])
            for instrument in INSTRUMENTS
        )
        turnover = sum(abs(weights[instrument] - previous[instrument]) for instrument in INSTRUMENTS)
        cost = turnover * one_way_cost_bps / 10000.0
        rows.append(
            {
                "decision_date": current["decision_date"],
                "entry_date": entry_day,
                "exit_date": exit_day,
                "gross_return": gross,
                "turnover": turnover,
                "cost_return": cost,
                "net_return": gross - cost,
                "gross_weight": sum(abs(value) for value in weights.values()),
                "net_usd_factor_weight": sum(weights.values()),
                "active_instruments": sum(value != 0 for value in weights.values()),
                "longs": sorted(instrument for instrument, value in weights.items() if value > 0),
                "shorts": sorted(instrument for instrument, value in weights.items() if value < 0),
            }
        )
        previous = weights
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_return"]) for row in rows]
    equity = peak = drawdown = 0.0
    annual: dict[str, float] = defaultdict(float)
    for row, value in zip(rows, values):
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
        annual[row["entry_date"][:4]] += value
    deviation = statistics.stdev(values) if len(values) > 1 else None
    return {
        "week_count": len(values),
        "average_weekly_net_return": statistics.fmean(values) if values else None,
        "median_weekly_net_return": statistics.median(values) if values else None,
        "positive_week_rate": sum(value > 0 for value in values) / len(values) if values else None,
        "annualized_log_return": statistics.fmean(values) * 52 if values else None,
        "annualized_volatility": deviation * math.sqrt(52) if deviation is not None else None,
        "annualized_sharpe_zero_rate": statistics.fmean(values) / deviation * math.sqrt(52) if deviation else None,
        "maximum_log_drawdown": drawdown if values else None,
        "positive_year_rate": sum(value > 0 for value in annual.values()) / len(annual) if annual else None,
        "year_count": len(annual),
        "average_weekly_turnover": statistics.fmean(float(row["turnover"]) for row in rows) if rows else None,
        "average_active_instruments": statistics.fmean(float(row["active_instruments"]) for row in rows) if rows else None,
    }


def evaluate(path: Path, one_way_cost_bps: float = 5.0) -> dict[str, Any]:
    days, panel = load_daily_spot(path)
    targets = target_series(days, panel)
    primary = portfolio_rows(days, panel, targets, one_way_cost_bps=one_way_cost_bps)
    first, second = int(len(primary) * 0.6), int(len(primary) * 0.8)
    partitions = {
        "development": primary[:first],
        "chronological_oos": primary[first:second],
        "dated_confirmation": primary[second:],
    }
    controls = {
        name.lower(): portfolio_rows(days, panel, targets, control=name, one_way_cost_bps=one_way_cost_bps)
        for name in ("OPPOSITE", "STALE", "RANDOM", "USD_FACTOR")
    }
    dated_entries = {row["entry_date"] for row in partitions["dated_confirmation"]}
    control_dated = {
        name: summarize([row for row in rows if row["entry_date"] in dated_entries])
        for name, rows in controls.items()
    }
    dated = summarize(partitions["dated_confirmation"])
    return {
        "schema": "FX_G10_TIME_SERIES_MOMENTUM_SPOT_DIAGNOSTIC_RESULT_V1",
        "strategy": "G10_DAILY_TSMOM_21_63_126_WEEKLY_V1",
        "interpretation": "SPOT_ONLY_DIAGNOSTIC_NOT_FINANCING_INCLUSIVE",
        "promotion_eligible": False,
        "promotion_blockers": ["HISTORICAL_FINANCING_OR_FORWARD_POINTS_UNAVAILABLE"],
        "instruments": list(INSTRUMENTS),
        "quote_normalization": "USD_VALUE_OF_ONE_UNIT_FOREIGN_CURRENCY",
        "cost_model": {"one_way_cost_bps_per_unit_turnover": one_way_cost_bps},
        "common_daily_observation_count": len(days),
        "target_week_count": len(targets),
        "portfolio_week_count": len(primary),
        "window_start": primary[0]["entry_date"] if primary else None,
        "window_end": primary[-1]["exit_date"] if primary else None,
        "partitions": {name: summarize(rows) for name, rows in partitions.items()},
        "controls_dated_confirmation": control_dated,
        "dated_control_edge": {
            name: dated["average_weekly_net_return"] - summary["average_weekly_net_return"]
            for name, summary in control_dated.items()
        },
        "rows": primary,
    }
