from __future__ import annotations

import csv
import gzip
import hashlib
import math
from pathlib import Path
from typing import Any

from .g10_value import _month_label, _month_number, load_spot, summarize


CURRENCIES = ("EUR", "GBP", "JPY", "CAD", "SEK", "NOK")


def load_industrial_production(path: Path) -> dict[str, dict[int, float]]:
    panel = {currency: {} for currency in CURRENCIES}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            currency = row["currency"]
            if currency in panel:
                panel[currency][_month_number(row["month"])] = float(row["industrial_production_index"])
    return panel


def momentum_signals(spot: dict[str, dict[str, float]], production: dict[str, dict[int, float]], formation_months: int = 60, lag_months: int = 2) -> dict[str, dict[str, float]]:
    signals = {}
    for month, prices in sorted(spot.items()):
        decision = _month_number(month)
        current_period = decision - lag_months
        prior_period = current_period - formation_months
        values = {}
        for currency in CURRENCIES:
            current = production.get(currency, {}).get(current_period)
            prior = production.get(currency, {}).get(prior_period)
            if currency not in prices or current is None or prior is None or current <= 0 or prior <= 0:
                continue
            values[currency] = math.log(current / prior)
        if len(values) == len(CURRENCIES):
            signals[month] = values
    return signals


def _weights(values: dict[str, float], reverse: bool = False) -> dict[str, float]:
    ordered = sorted(values, key=lambda currency: (values[currency], currency), reverse=True)
    weights = {currency: (0.25 if currency in ordered[:2] else -0.25 if currency in ordered[-2:] else 0.0) for currency in ordered}
    return {currency: -weight for currency, weight in weights.items()} if reverse else weights


def _permuted(values: dict[str, float], month: str) -> dict[str, float]:
    currencies = sorted(values)
    labels = sorted(currencies, key=lambda value: hashlib.sha256(f"20261017:{month}:{value}".encode()).hexdigest())
    return {currency: values[label] for currency, label in zip(currencies, labels)}


def portfolio_rows(spot: dict[str, dict[str, float]], signals: dict[str, dict[str, float]], one_way_cost_bps: float = 5.0, control: str = "PRIMARY") -> list[dict[str, Any]]:
    rows = []
    previous_weights = {currency: 0.0 for currency in CURRENCIES}
    prior_signals = None
    for month, current_signals in sorted(signals.items()):
        next_month = _month_label(_month_number(month) + 1)
        if next_month not in spot or any(currency not in spot[month] or currency not in spot[next_month] for currency in CURRENCIES):
            prior_signals = current_signals
            continue
        source = current_signals
        if control == "STALE":
            if prior_signals is None:
                prior_signals = current_signals
                continue
            source = prior_signals
        elif control == "PERMUTATION":
            source = _permuted(current_signals, month)
        weights = _weights(source, reverse=control == "OPPOSITE")
        gross = sum(weights[currency] * math.log(spot[next_month][currency] / spot[month][currency]) for currency in CURRENCIES)
        turnover = sum(abs(weights[currency] - previous_weights[currency]) for currency in CURRENCIES)
        cost = turnover * one_way_cost_bps / 10000
        rows.append({"month": month, "next_month": next_month, "gross_return": gross, "turnover": turnover, "cost_return": cost, "net_return": gross - cost, "longs": sorted(currency for currency, weight in weights.items() if weight > 0), "shorts": sorted(currency for currency, weight in weights.items() if weight < 0)})
        previous_weights = weights
        prior_signals = current_signals
    return rows


def evaluate(spot_path: Path, production_path: Path, one_way_cost_bps: float = 5.0) -> dict[str, Any]:
    spot = load_spot(spot_path)
    signals = momentum_signals(spot, load_industrial_production(production_path))
    primary = portfolio_rows(spot, signals, one_way_cost_bps)
    first, second = int(len(primary) * 0.6), int(len(primary) * 0.8)
    partitions = {"development": primary[:first], "chronological_oos": primary[first:second], "dated_confirmation": primary[second:]}
    controls = {name.lower(): portfolio_rows(spot, signals, one_way_cost_bps, name) for name in ("OPPOSITE", "STALE", "PERMUTATION")}
    dated = summarize(partitions["dated_confirmation"])
    dated_months = {row["month"] for row in partitions["dated_confirmation"]}
    control_dated = {name: summarize([row for row in rows if row["month"] in dated_months]) for name, rows in controls.items()}
    return {"schema": "FX_G10_INDUSTRIAL_PRODUCTION_MOMENTUM_RESULT_V1", "strategy": "INDUSTRIAL_PRODUCTION_MOMENTUM_60M_TOP2_BOTTOM2", "currencies": list(CURRENCIES), "cost_model": {"one_way_cost_bps_per_unit_turnover": one_way_cost_bps}, "signal_month_count": len(signals), "portfolio_month_count": len(primary), "window_start": primary[0]["month"] if primary else None, "window_end": primary[-1]["next_month"] if primary else None, "partitions": {name: summarize(rows) for name, rows in partitions.items()}, "controls_dated_confirmation": control_dated, "dated_control_edge": {name: dated["average_monthly_net_return"] - summary["average_monthly_net_return"] for name, summary in control_dated.items()}, "rows": primary}
