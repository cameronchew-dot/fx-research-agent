from __future__ import annotations

import csv
import gzip
import hashlib
import math
import statistics
from pathlib import Path
from typing import Any

from .g10_value import INSTRUMENT_CURRENCY, load_cpi, load_spot


def _month_number(value: str) -> int:
    year, month = value[:7].split("-")
    return int(year) * 12 + int(month) - 1


def _month_label(number: int) -> str:
    return f"{number // 12:04d}-{number % 12 + 1:02d}"


def load_policy_rates(path: Path) -> dict[str, dict[str, float]]:
    panel: dict[str, dict[str, float]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            panel.setdefault(row["month"], {})[row["currency"]] = float(row["policy_rate_percent"])
    return panel


def _inflation_as_of(series: list[tuple[int, float]], as_of: int, lag: int = 2) -> float | None:
    available = [(period, value) for period, value in series if period + lag <= as_of]
    if not available:
        return None
    period, current = available[-1]
    prior = {item_period: value for item_period, value in series}.get(period - 12)
    if prior is None or current <= 0 or prior <= 0:
        return None
    return 100 * math.log(current / prior)


def stance_shifts(spot: dict[str, dict[str, float]], policy: dict[str, dict[str, float]], cpi: dict[str, list[tuple[int, float]]]) -> dict[str, dict[str, dict[str, float]]]:
    result = {}
    for month, prices in sorted(spot.items()):
        number = _month_number(month)
        prior_month = _month_label(number - 3)
        if month not in policy or prior_month not in policy or prior_month not in spot:
            continue
        current_us_inflation = _inflation_as_of(cpi.get("USD", []), number)
        prior_us_inflation = _inflation_as_of(cpi.get("USD", []), number - 3)
        if current_us_inflation is None or prior_us_inflation is None or "USD" not in policy[month] or "USD" not in policy[prior_month]:
            continue
        values = {}
        for currency in INSTRUMENT_CURRENCY.values():
            if currency not in prices or currency not in spot[prior_month] or currency not in policy[month] or currency not in policy[prior_month]:
                continue
            current_inflation = _inflation_as_of(cpi.get(currency, []), number)
            prior_inflation = _inflation_as_of(cpi.get(currency, []), number - 3)
            if current_inflation is None or prior_inflation is None:
                continue
            current_relative = (policy[month][currency] - current_inflation) - (policy[month]["USD"] - current_us_inflation)
            prior_relative = (policy[prior_month][currency] - prior_inflation) - (policy[prior_month]["USD"] - prior_us_inflation)
            values[currency] = {"stance_shift_pp": current_relative - prior_relative, "spot_confirmation_return": math.log(prices[currency] / spot[prior_month][currency])}
        if len(values) == 9:
            result[month] = values
    return result


def _directions(values: dict[str, dict[str, float]], threshold: float = 0.25) -> dict[str, int]:
    return {currency: (1 if facts["stance_shift_pp"] > 0 else -1) for currency, facts in values.items() if abs(facts["stance_shift_pp"]) >= threshold and facts["stance_shift_pp"] * facts["spot_confirmation_return"] > 0}


def _permuted_values(values: dict[str, dict[str, float]], month: str) -> dict[str, dict[str, float]]:
    currencies = sorted(values)
    labels = sorted(currencies, key=lambda value: hashlib.sha256(f"20261017:{month}:{value}".encode()).hexdigest())
    return {currency: {**values[currency], "stance_shift_pp": values[label]["stance_shift_pp"]} for currency, label in zip(currencies, labels)}


def _month_return(prices: dict[str, float], next_prices: dict[str, float], directions: dict[str, int], round_trip_cost_bps: float) -> dict[str, Any]:
    if not directions:
        return {"active_currency_count": 0, "gross_return": 0.0, "cost_return": 0.0, "net_return": 0.0, "directions": {}}
    weight = 1 / len(directions)
    gross = sum(weight * direction * math.log(next_prices[currency] / prices[currency]) for currency, direction in directions.items())
    cost = round_trip_cost_bps / 10000
    return {"active_currency_count": len(directions), "gross_return": gross, "cost_return": cost, "net_return": gross - cost, "directions": dict(sorted(directions.items()))}


def strategy_rows(spot: dict[str, dict[str, float]], shifts: dict[str, dict[str, dict[str, float]]], round_trip_cost_bps: float = 10.0) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    primary = []
    controls = {"opposite": [], "stale": [], "permutation": []}
    prior_directions: dict[str, int] = {}
    for month, values in sorted(shifts.items()):
        next_month = _month_label(_month_number(month) + 1)
        if next_month not in spot:
            continue
        directions = _directions(values)
        primary_result = _month_return(spot[month], spot[next_month], directions, round_trip_cost_bps)
        if directions:
            primary.append({"month": month, "next_month": next_month, **primary_result})
            control_directions = {
                "opposite": {currency: -direction for currency, direction in directions.items()},
                "stale": prior_directions,
                "permutation": _directions(_permuted_values(values, month)),
            }
            for name, selected in control_directions.items():
                controls[name].append({"month": month, "next_month": next_month, **_month_return(spot[month], spot[next_month], selected, round_trip_cost_bps)})
        prior_directions = directions
    return primary, controls


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_return"]) for row in rows]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return {"active_month_count": len(values), "average_monthly_net_return": statistics.fmean(values) if values else None, "median_monthly_net_return": statistics.median(values) if values else None, "positive_month_rate": sum(value > 0 for value in values) / len(values) if values else None, "annualized_volatility": statistics.stdev(values) * math.sqrt(12) if len(values) > 1 else None, "maximum_log_drawdown": drawdown if values else None, "average_active_currency_count": statistics.fmean(row["active_currency_count"] for row in rows) if rows else None}


def evaluate(spot_path: Path, policy_path: Path, cpi_path: Path, round_trip_cost_bps: float = 10.0) -> dict[str, Any]:
    spot = load_spot(spot_path)
    shifts = stance_shifts(spot, load_policy_rates(policy_path), load_cpi(cpi_path))
    primary, controls = strategy_rows(spot, shifts, round_trip_cost_bps)
    first = int(len(primary) * 0.6)
    second = int(len(primary) * 0.8)
    partitions = {"development": primary[:first], "chronological_oos": primary[first:second], "dated_confirmation": primary[second:]}
    dated_months = {row["month"] for row in partitions["dated_confirmation"]}
    control_dated = {name: summarize([row for row in rows if row["month"] in dated_months]) for name, rows in controls.items()}
    dated = summarize(partitions["dated_confirmation"])
    return {"schema": "FX_G10_REAL_POLICY_STANCE_RESULT_V1", "strategy": "REAL_POLICY_STANCE_SHIFT_3M_SPOT_CONFIRMED", "cost_model": {"round_trip_cost_bps_per_active_month": round_trip_cost_bps}, "complete_shift_month_count": len(shifts), "active_month_count": len(primary), "window_start": primary[0]["month"] if primary else None, "window_end": primary[-1]["next_month"] if primary else None, "partitions": {name: summarize(rows) for name, rows in partitions.items()}, "controls_dated_confirmation": control_dated, "dated_control_edge": {name: dated["average_monthly_net_return"] - summary["average_monthly_net_return"] for name, summary in control_dated.items()}, "rows": primary}
