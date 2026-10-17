from __future__ import annotations

import csv
import gzip
import hashlib
import math
import statistics
from pathlib import Path
from typing import Any


INSTRUMENT_CURRENCY = {"EUR_USD": "EUR", "GBP_USD": "GBP", "USD_JPY": "JPY", "USD_CHF": "CHF", "USD_CAD": "CAD", "AUD_USD": "AUD", "NZD_USD": "NZD", "USD_SEK": "SEK", "USD_NOK": "NOK"}


def _month_number(value: str) -> int:
    if "-Q" in value:
        year, quarter = value.split("-Q")
        return int(year) * 12 + int(quarter) * 3 - 1
    year, month = value[:7].split("-")
    return int(year) * 12 + int(month) - 1


def _month_label(number: int) -> str:
    return f"{number // 12:04d}-{number % 12 + 1:02d}"


def load_spot(path: Path) -> dict[str, dict[str, float]]:
    panel: dict[str, dict[str, float]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            currency = INSTRUMENT_CURRENCY.get(row["instrument"])
            if currency:
                panel.setdefault(row["month"], {})[currency] = float(row["normalized_usd_per_foreign_currency"])
    return panel


def load_cpi(path: Path) -> dict[str, list[tuple[int, float]]]:
    panel: dict[str, list[tuple[int, float]]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            panel.setdefault(row["currency"], []).append((_month_number(row["period"]), float(row["cpi_index"])))
    for values in panel.values():
        values.sort()
    return panel


def _available_cpi(series: list[tuple[int, float]], as_of_month: int, lag: int = 2) -> float | None:
    eligible = [value for period, value in series if period + lag <= as_of_month]
    return eligible[-1] if eligible else None


def value_signals(spot: dict[str, dict[str, float]], cpi: dict[str, list[tuple[int, float]]], lookback: int = 60, lag: int = 2) -> dict[str, dict[str, float]]:
    result = {}
    for month, prices in sorted(spot.items()):
        number = _month_number(month)
        old_month = _month_label(number - lookback)
        old_prices = spot.get(old_month, {})
        values = {}
        for currency in INSTRUMENT_CURRENCY.values():
            now_foreign = _available_cpi(cpi.get(currency, []), number, lag)
            now_us = _available_cpi(cpi.get("USD", []), number, lag)
            old_foreign = _available_cpi(cpi.get(currency, []), number - lookback, lag)
            old_us = _available_cpi(cpi.get("USD", []), number - lookback, lag)
            if currency not in prices or currency not in old_prices or None in (now_foreign, now_us, old_foreign, old_us):
                continue
            q_now = math.log(prices[currency]) + math.log(float(now_foreign) / float(now_us))
            q_old = math.log(old_prices[currency]) + math.log(float(old_foreign) / float(old_us))
            values[currency] = -(q_now - q_old)
        if len(values) == 9:
            result[month] = values
    return result


def _weights(ranks: dict[str, float], reverse: bool = False) -> dict[str, float]:
    ordered = sorted(ranks, key=lambda currency: (ranks[currency], currency), reverse=not reverse)
    return {currency: (1 / 6 if currency in ordered[:3] else -1 / 6 if currency in ordered[-3:] else 0.0) for currency in ordered}


def _permuted(signals: dict[str, float], month: str) -> dict[str, float]:
    currencies = sorted(signals)
    labels = sorted(currencies, key=lambda value: hashlib.sha256(f"20261017:{month}:{value}".encode()).hexdigest())
    return {currency: signals[label] for currency, label in zip(currencies, labels)}


def portfolio_rows(spot: dict[str, dict[str, float]], signals: dict[str, dict[str, float]], one_way_cost_bps: float = 5.0, control: str = "PRIMARY") -> list[dict[str, Any]]:
    months = sorted(signals)
    rows = []
    previous_weights = {currency: 0.0 for currency in INSTRUMENT_CURRENCY.values()}
    prior_signals = None
    for month in months:
        next_month = _month_label(_month_number(month) + 1)
        if next_month not in spot or len(spot[month]) != 9 or len(spot[next_month]) != 9:
            prior_signals = signals[month]
            continue
        source = signals[month]
        if control == "STALE":
            if prior_signals is None:
                prior_signals = source
                continue
            source = prior_signals
        elif control == "PERMUTATION":
            source = _permuted(source, month)
        weights = _weights(source, reverse=control == "OPPOSITE")
        gross = sum(weights[currency] * math.log(spot[next_month][currency] / spot[month][currency]) for currency in weights)
        turnover = sum(abs(weights[currency] - previous_weights[currency]) for currency in weights)
        cost = turnover * one_way_cost_bps / 10000
        rows.append({"month": month, "next_month": next_month, "gross_return": gross, "turnover": turnover, "cost_return": cost, "net_return": gross - cost, "longs": sorted(currency for currency, weight in weights.items() if weight > 0), "shorts": sorted(currency for currency, weight in weights.items() if weight < 0)})
        previous_weights = weights
        prior_signals = signals[month]
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_return"]) for row in rows]
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return {"month_count": len(values), "average_monthly_net_return": statistics.fmean(values) if values else None, "median_monthly_net_return": statistics.median(values) if values else None, "positive_month_rate": sum(value > 0 for value in values) / len(values) if values else None, "annualized_volatility": statistics.stdev(values) * math.sqrt(12) if len(values) > 1 else None, "maximum_log_drawdown": drawdown if values else None}


def evaluate(spot_path: Path, cpi_path: Path, one_way_cost_bps: float = 5.0) -> dict[str, Any]:
    spot = load_spot(spot_path)
    signals = value_signals(spot, load_cpi(cpi_path))
    primary = portfolio_rows(spot, signals, one_way_cost_bps)
    boundaries = (int(len(primary) * 0.6), int(len(primary) * 0.8))
    partitions = {"development": primary[:boundaries[0]], "chronological_oos": primary[boundaries[0]:boundaries[1]], "dated_confirmation": primary[boundaries[1]:]}
    controls = {name.lower(): portfolio_rows(spot, signals, one_way_cost_bps, name) for name in ("OPPOSITE", "STALE", "PERMUTATION")}
    dated = summarize(partitions["dated_confirmation"])
    dated_months = {row["month"] for row in partitions["dated_confirmation"]}
    control_dated = {
        name: summarize([row for row in rows if row["month"] in dated_months])
        for name, rows in controls.items()
    }
    return {"schema": "FX_G10_REAL_VALUE_RESULT_V1", "strategy": "REAL_VALUE_60M", "cost_model": {"one_way_cost_bps_per_unit_turnover": one_way_cost_bps}, "signal_month_count": len(signals), "portfolio_month_count": len(primary), "window_start": primary[0]["month"] if primary else None, "window_end": primary[-1]["next_month"] if primary else None, "partitions": {name: summarize(rows) for name, rows in partitions.items()}, "controls_dated_confirmation": control_dated, "dated_control_edge": {name: dated["average_monthly_net_return"] - summary["average_monthly_net_return"] for name, summary in control_dated.items()}, "rows": primary}
