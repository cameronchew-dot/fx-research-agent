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


ASSET_CLASSES = {
    "SPY": "EQUITY",
    "EFA": "EQUITY",
    "IEF": "BOND",
    "TLT": "BOND",
    "GLD": "REAL_ASSET",
    "DBC": "REAL_ASSET",
    "UUP": "CURRENCY",
}
ASSETS = tuple(ASSET_CLASSES)
CASH_PROXY = "BIL"
ALL_SYMBOLS = (*ASSETS, CASH_PROXY)
TREND_LOOKBACK_DAYS = 252
VOLATILITY_LOOKBACK_DAYS = 63
ASSET_WEIGHT_CAP = 0.25
CLASS_WEIGHT_CAPS = {
    "EQUITY": 0.40,
    "BOND": 0.40,
    "REAL_ASSET": 0.40,
    "CURRENCY": 0.20,
}


def load_adjusted_prices(path: Path) -> tuple[list[str], dict[str, dict[str, float]]]:
    panel: dict[str, dict[str, float]] = defaultdict(dict)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            symbol = row["symbol"]
            if symbol not in ALL_SYMBOLS:
                continue
            value = float(row["adjusted_close"])
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"invalid adjusted close: {row['date']}:{symbol}")
            if symbol in panel[row["date"]]:
                raise ValueError(f"duplicate adjusted close: {row['date']}:{symbol}")
            panel[row["date"]][symbol] = value
    complete = {
        day: values
        for day, values in panel.items()
        if all(symbol in values for symbol in ALL_SYMBOLS)
    }
    return sorted(complete), complete


def _month_end_dates(days: list[str]) -> list[str]:
    by_month: dict[str, list[str]] = defaultdict(list)
    for day in days:
        by_month[day[:7]].append(day)
    return [max(values) for _, values in sorted(by_month.items())]


def _volatility(
    days: list[str],
    panel: dict[str, dict[str, float]],
    day_index: int,
    symbol: str,
) -> float | None:
    if day_index < VOLATILITY_LOOKBACK_DAYS:
        return None
    returns = [
        math.log(panel[days[index]][symbol] / panel[days[index - 1]][symbol])
        for index in range(day_index - VOLATILITY_LOOKBACK_DAYS + 1, day_index + 1)
    ]
    value = statistics.stdev(returns)
    return value if value > 0 else None


def _capped_weights(active: set[str], volatilities: dict[str, float]) -> dict[str, float]:
    raw = {symbol: 1.0 / volatilities[symbol] for symbol in active if symbol in volatilities}
    total = sum(raw.values())
    weights = {symbol: 0.0 for symbol in ASSETS}
    if total <= 0:
        return weights
    for symbol, value in raw.items():
        weights[symbol] = min(ASSET_WEIGHT_CAP, value / total)
    for asset_class, cap in CLASS_WEIGHT_CAPS.items():
        members = [symbol for symbol in ASSETS if ASSET_CLASSES[symbol] == asset_class]
        class_weight = sum(weights[symbol] for symbol in members)
        if class_weight > cap:
            scale = cap / class_weight
            for symbol in members:
                weights[symbol] *= scale
    return weights


def target_series(
    days: list[str],
    panel: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    index_by_day = {day: index for index, day in enumerate(days)}
    targets: list[dict[str, Any]] = []
    prior_primary: dict[str, float] | None = None
    for decision_day in _month_end_dates(days):
        day_index = index_by_day[decision_day]
        if day_index < TREND_LOOKBACK_DAYS or day_index + 1 >= len(days):
            continue
        trend_returns = {
            symbol: math.log(
                panel[days[day_index]][symbol]
                / panel[days[day_index - TREND_LOOKBACK_DAYS]][symbol]
            )
            for symbol in ASSETS
        }
        volatilities = {
            symbol: value
            for symbol in ASSETS
            if (value := _volatility(days, panel, day_index, symbol)) is not None
        }
        positive = {symbol for symbol, value in trend_returns.items() if value > 0}
        negative = {symbol for symbol, value in trend_returns.items() if value <= 0}
        primary = _capped_weights(positive, volatilities)
        opposite = _capped_weights(negative, volatilities)
        buy_hold = _capped_weights(set(ASSETS), volatilities)
        random_active = {
            symbol
            for symbol in ASSETS
            if hashlib.sha256(f"20261109:{decision_day}:{symbol}".encode()).digest()[0] % 2
        }
        random_control = _capped_weights(random_active, volatilities)
        targets.append(
            {
                "decision_date": decision_day,
                "effective_date": days[day_index + 1],
                "PRIMARY": primary,
                "OPPOSITE": opposite,
                "STALE": prior_primary or {symbol: 0.0 for symbol in ASSETS},
                "RANDOM": random_control,
                "BUY_HOLD": buy_hold,
                "trend_log_returns": trend_returns,
                "daily_volatility": volatilities,
            }
        )
        prior_primary = primary
    return targets


def portfolio_rows(
    panel: dict[str, dict[str, float]],
    targets: list[dict[str, Any]],
    *,
    control: str = "PRIMARY",
    one_way_cost_bps: float = 10.0,
) -> list[dict[str, Any]]:
    previous = {symbol: 0.0 for symbol in ASSETS}
    rows: list[dict[str, Any]] = []
    for current, following in zip(targets, targets[1:]):
        weights = current[control]
        entry_day = current["effective_date"]
        exit_day = following["effective_date"]
        gross_weight = sum(weights.values())
        cash_weight = max(0.0, 1.0 - gross_weight)
        cash_return = math.log(panel[exit_day][CASH_PROXY] / panel[entry_day][CASH_PROXY])
        risky_return = sum(
            weight * math.log(panel[exit_day][symbol] / panel[entry_day][symbol])
            for symbol, weight in weights.items()
        )
        turnover = sum(abs(weights[symbol] - previous[symbol]) for symbol in ASSETS)
        cost = turnover * one_way_cost_bps / 10000.0
        net_return = risky_return + cash_weight * cash_return - cost
        rows.append(
            {
                "decision_date": current["decision_date"],
                "entry_date": entry_day,
                "exit_date": exit_day,
                "net_return": net_return,
                "cash_return": cash_return,
                "excess_cash_return": net_return - cash_return,
                "risky_gross_weight": gross_weight,
                "cash_weight": cash_weight,
                "turnover": turnover,
                "cost_return": cost,
                "active_assets": sorted(symbol for symbol, weight in weights.items() if weight > 0),
            }
        )
        previous = weights
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_return"]) for row in rows]
    excess = [float(row["excess_cash_return"]) for row in rows]
    equity = peak = drawdown = 0.0
    annual: dict[str, float] = defaultdict(float)
    for row, value in zip(rows, values):
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
        annual[row["entry_date"][:4]] += value
    deviation = statistics.stdev(values) if len(values) > 1 else None
    excess_deviation = statistics.stdev(excess) if len(excess) > 1 else None
    return {
        "month_count": len(rows),
        "average_monthly_net_return": statistics.fmean(values) if values else None,
        "average_monthly_excess_cash_return": statistics.fmean(excess) if excess else None,
        "annualized_log_return": statistics.fmean(values) * 12 if values else None,
        "annualized_volatility": deviation * math.sqrt(12) if deviation is not None else None,
        "annualized_sharpe_zero_rate": statistics.fmean(values) / deviation * math.sqrt(12) if deviation else None,
        "annualized_information_ratio_over_cash": statistics.fmean(excess) / excess_deviation * math.sqrt(12) if excess_deviation else None,
        "positive_month_rate": sum(value > 0 for value in values) / len(values) if values else None,
        "positive_year_rate": sum(value > 0 for value in annual.values()) / len(annual) if annual else None,
        "year_count": len(annual),
        "maximum_log_drawdown": drawdown if values else None,
        "average_turnover": statistics.fmean(float(row["turnover"]) for row in rows) if rows else None,
        "average_risky_gross_weight": statistics.fmean(float(row["risky_gross_weight"]) for row in rows) if rows else None,
        "average_active_asset_count": statistics.fmean(len(row["active_assets"]) for row in rows) if rows else None,
    }


def evaluate(path: Path, one_way_cost_bps: float = 10.0) -> dict[str, Any]:
    days, panel = load_adjusted_prices(path)
    targets = target_series(days, panel)
    primary = portfolio_rows(panel, targets, one_way_cost_bps=one_way_cost_bps)
    first, second = int(len(primary) * 0.6), int(len(primary) * 0.8)
    partitions = {
        "development": primary[:first],
        "chronological_oos": primary[first:second],
        "dated_confirmation": primary[second:],
    }
    controls = {
        name.lower(): portfolio_rows(panel, targets, control=name, one_way_cost_bps=one_way_cost_bps)
        for name in ("OPPOSITE", "STALE", "RANDOM", "BUY_HOLD")
    }
    dated_entries = {row["entry_date"] for row in partitions["dated_confirmation"]}
    control_dated = {
        name: summarize([row for row in rows if row["entry_date"] in dated_entries])
        for name, rows in controls.items()
    }
    dated = summarize(partitions["dated_confirmation"])
    return {
        "schema": "CROSS_ASSET_ETF_TREND_DIAGNOSTIC_RESULT_V1",
        "strategy": "CROSS_ASSET_ETF_12M_TREND_LONG_OR_CASH_V1",
        "interpretation": "DISCOVERY_SOURCE_REQUIRES_INDEPENDENT_CROSS_SOURCE_CONFIRMATION",
        "promotion_eligible": False,
        "promotion_blockers": ["INDEPENDENT_ADJUSTED_PRICE_SOURCE_CONFIRMATION_REQUIRED"],
        "assets": list(ASSETS),
        "cash_proxy": CASH_PROXY,
        "cost_model": {"one_way_cost_bps_per_unit_turnover": one_way_cost_bps},
        "common_daily_observation_count": len(days),
        "portfolio_month_count": len(primary),
        "window_start": primary[0]["entry_date"] if primary else None,
        "window_end": primary[-1]["exit_date"] if primary else None,
        "partitions": {name: summarize(rows) for name, rows in partitions.items()},
        "controls_dated_confirmation": control_dated,
        "dated_average_excess_cash_edge": {
            name: dated["average_monthly_excess_cash_return"] - summary["average_monthly_excess_cash_return"]
            for name, summary in control_dated.items()
        },
        "dated_sharpe_edge": {
            name: dated["annualized_sharpe_zero_rate"] - summary["annualized_sharpe_zero_rate"]
            for name, summary in control_dated.items()
        },
        "rows": primary,
    }
