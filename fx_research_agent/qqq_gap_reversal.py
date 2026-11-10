from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
REQUIRED_TIMES = ("09:30", "09:31", "09:59", "15:59")
CONTROL_NAMES = ("primary", "always", "opposite", "prior_day")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def load_required_minutes(path: Path, *, expected_symbol: str = "QQQ") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prior_timestamp: datetime | None = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw.get("symbol") != expected_symbol:
                raise ValueError(f"gap-reversal campaign accepts {expected_symbol} only")
            timestamp = _utc(raw["timestamp_utc"])
            if prior_timestamp is not None and timestamp <= prior_timestamp:
                raise ValueError("minute bars must be strictly increasing")
            prior_timestamp = timestamp
            if timestamp.astimezone(NEW_YORK).strftime("%H:%M") not in REQUIRED_TIMES:
                continue
            values = {
                key: float(raw[key])
                for key in ("open", "high", "low", "close")
            }
            if any(not math.isfinite(value) or value <= 0 for value in values.values()):
                raise ValueError(f"invalid {expected_symbol} price at {raw['timestamp_utc']}")
            if values["low"] > min(values["open"], values["close"]):
                raise ValueError(f"invalid {expected_symbol} low at {raw['timestamp_utc']}")
            if values["high"] < max(values["open"], values["close"]):
                raise ValueError(f"invalid {expected_symbol} high at {raw['timestamp_utc']}")
            rows.append({"timestamp_utc": timestamp, **values})
    return rows


def build_session_rows(
    minute_rows: list[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    sessions: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in minute_rows:
        local = row["timestamp_utc"].astimezone(NEW_YORK)
        day = local.date().isoformat()
        if day < start_date or day > end_date or local.weekday() >= 5:
            continue
        clock = local.strftime("%H:%M")
        if clock in sessions[day]:
            raise ValueError(f"duplicate QQQ regular-session minute: {day} {clock}")
        sessions[day][clock] = row

    output: list[dict[str, Any]] = []
    previous_close: float | None = None
    previous_negative_gap: bool | None = None
    for day in sorted(sessions):
        bars = sessions[day]
        if not all(clock in bars for clock in REQUIRED_TIMES):
            continue
        current_close = float(bars["15:59"]["close"])
        if previous_close is not None:
            overnight_return = float(bars["09:30"]["open"]) / previous_close - 1.0
            negative_gap = overnight_return < 0.0
            execution_return = (
                float(bars["09:59"]["close"]) / float(bars["09:31"]["open"]) - 1.0
            )
            output.append(
                {
                    "date": day,
                    "overnight_return": overnight_return,
                    "execution_gross_return": execution_return,
                    "primary_active": negative_gap,
                    "always_active": True,
                    "opposite_active": not negative_gap,
                    "prior_day_active": previous_negative_gap is True,
                }
            )
            previous_negative_gap = negative_gap
        previous_close = current_close
    return output


def strategy_daily_return(row: dict[str, Any], control: str, one_way_cost_bps: float) -> float:
    if not row[f"{control}_active"]:
        return 0.0
    return float(row["execution_gross_return"]) - 2.0 * one_way_cost_bps / 10000.0


def _compound(returns: list[float]) -> float:
    value = 1.0
    for result in returns:
        value *= 1.0 + result
    return value - 1.0


def _maximum_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    equity = peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def summarize(rows: list[dict[str, Any]], control: str, one_way_cost_bps: float) -> dict[str, Any]:
    daily = [strategy_daily_return(row, control, one_way_cost_bps) for row in rows]
    trades = [value for row, value in zip(rows, daily) if row[f"{control}_active"]]
    gross = [
        float(row["execution_gross_return"])
        for row in rows
        if row[f"{control}_active"]
    ]
    mean_daily = statistics.fmean(daily) if daily else None
    daily_std = statistics.stdev(daily) if len(daily) > 1 else None
    monthly: dict[str, list[float]] = defaultdict(list)
    yearly: dict[str, list[float]] = defaultdict(list)
    for row, value in zip(rows, daily):
        monthly[row["date"][:7]].append(value)
        yearly[row["date"][:4]].append(value)
    month_returns = [_compound(values) for _, values in sorted(monthly.items())]
    year_returns = [_compound(values) for _, values in sorted(yearly.items())]
    return {
        "session_count": len(rows),
        "trade_count": len(trades),
        "trades_per_week": len(trades) / len(rows) * 5.0 if rows else None,
        "positive_trade_rate": sum(value > 0 for value in trades) / len(trades) if trades else None,
        "average_gross_return_per_trade": statistics.fmean(gross) if gross else None,
        "average_net_return_per_trade": statistics.fmean(trades) if trades else None,
        "median_net_return_per_trade": statistics.median(trades) if trades else None,
        "average_daily_net_return": mean_daily,
        "annualized_sharpe": (
            mean_daily / daily_std * math.sqrt(252)
            if mean_daily is not None and daily_std is not None and daily_std > 0
            else None
        ),
        "positive_month_rate": sum(value > 0 for value in month_returns) / len(month_returns) if month_returns else None,
        "month_count": len(month_returns),
        "compounded_return": _compound(daily),
        "maximum_drawdown": _maximum_drawdown(daily),
        "worst_calendar_year_return": min(year_returns) if year_returns else None,
    }


def newey_west_t_stat(values: list[float], *, lag: int = 5) -> float | None:
    count = len(values)
    if count < lag + 3:
        return None
    mean = statistics.fmean(values)
    centered = [value - mean for value in values]
    long_run_variance = sum(value * value for value in centered) / count
    for offset in range(1, lag + 1):
        covariance = sum(
            centered[index] * centered[index - offset]
            for index in range(offset, count)
        ) / count
        long_run_variance += 2.0 * (1.0 - offset / (lag + 1.0)) * covariance
    if long_run_variance <= 0:
        return None
    return mean / math.sqrt(long_run_variance / count)


def _partition(rows: list[dict[str, Any]], bounds: list[str]) -> list[dict[str, Any]]:
    return [row for row in rows if bounds[0] <= row["date"] <= bounds[1]]


def _cost_evaluation(
    rows: list[dict[str, Any]],
    campaign: dict[str, Any],
    one_way_cost_bps: float,
) -> dict[str, Any]:
    partitions = {
        name: _partition(rows, bounds)
        for name, bounds in campaign["partitions"].items()
    }
    validation_plus_dated = [
        row
        for row in rows
        if campaign["partitions"]["chronological_validation"][0]
        <= row["date"]
        <= campaign["partitions"]["dated_confirmation"][1]
    ]
    metrics = {
        name: {
            control: summarize(partition_rows, control, one_way_cost_bps)
            for control in CONTROL_NAMES
        }
        for name, partition_rows in partitions.items()
    }
    combined = {
        control: summarize(validation_plus_dated, control, one_way_cost_bps)
        for control in CONTROL_NAMES
    }
    primary_returns = [
        strategy_daily_return(row, "primary", one_way_cost_bps)
        for row in validation_plus_dated
    ]
    paired_t_stats: dict[str, float | None] = {}
    for control in ("always", "opposite", "prior_day"):
        comparator = [
            strategy_daily_return(row, control, one_way_cost_bps)
            for row in validation_plus_dated
        ]
        paired_t_stats[control] = newey_west_t_stat(
            [left - right for left, right in zip(primary_returns, comparator)]
        )

    gates = campaign["review_gates"]
    checks = {
        **{
            f"minimum_primary_trades_{name}":
            metrics[name]["primary"]["trade_count"] >= minimum
            for name, minimum in gates["minimum_primary_trades"].items()
        },
        "average_daily_net_positive_all_partitions": all(
            metrics[name]["primary"]["average_daily_net_return"] is not None
            and metrics[name]["primary"]["average_daily_net_return"] > 0
            for name in campaign["partitions"]
        ),
        "validation_and_dated_sharpe_minimum": all(
            metrics[name]["primary"]["annualized_sharpe"] is not None
            and metrics[name]["primary"]["annualized_sharpe"]
            >= float(gates["validation_and_dated_sharpe_minimum"])
            for name in ("chronological_validation", "dated_confirmation")
        ),
        "validation_plus_dated_positive_month_rate": (
            combined["primary"]["positive_month_rate"] is not None
            and combined["primary"]["positive_month_rate"]
            >= float(gates["validation_plus_dated_positive_month_rate_minimum"])
        ),
        "validation_plus_dated_drawdown": (
            combined["primary"]["maximum_drawdown"] is not None
            and combined["primary"]["maximum_drawdown"]
            >= float(gates["validation_plus_dated_maximum_drawdown_floor"])
        ),
        "validation_plus_dated_beats_all_controls": all(
            combined["primary"]["average_daily_net_return"]
            > combined[control]["average_daily_net_return"]
            for control in ("always", "opposite", "prior_day")
        ),
        "validation_plus_dated_newey_west_t_stats": all(
            value is not None
            and value >= float(gates["validation_plus_dated_newey_west_t_stat_minimum"])
            for value in paired_t_stats.values()
        ),
    }
    return {
        "one_way_cost_bps": one_way_cost_bps,
        "partitions": metrics,
        "validation_plus_dated": combined,
        "paired_newey_west_t_stats": paired_t_stats,
        "gates": checks,
        "passed": all(checks.values()),
    }


def evaluate(path: Path, campaign: dict[str, Any]) -> dict[str, Any]:
    minute_rows = load_required_minutes(path, expected_symbol=campaign["instrument"])
    population = campaign["population"]
    sessions = build_session_rows(
        minute_rows,
        start_date=population["window_start"],
        end_date=population["window_end_inclusive"],
    )
    exact = campaign["exact_specification"]
    costs = {
        "primary": _cost_evaluation(
            sessions, campaign, float(exact["primary_one_way_cost_bps"])
        ),
        "stress": _cost_evaluation(
            sessions, campaign, float(exact["stress_one_way_cost_bps"])
        ),
    }
    passed = all(result["passed"] for result in costs.values())
    return {
        "schema": "QQQ_OVERNIGHT_GAP_FIRST_HALF_HOUR_REVERSAL_RESULT_V1",
        "campaign_id": campaign["campaign_id"],
        "status": (
            "HISTORICAL_GATE_PASS_REQUIRES_FRESH_FORWARD_REVIEW"
            if passed
            else "HISTORICAL_GATE_FAIL"
        ),
        "population": {
            "required_timestamp_bar_count": len(minute_rows),
            "complete_session_count": len(sessions),
            "session_start": sessions[0]["date"] if sessions else None,
            "session_end": sessions[-1]["date"] if sessions else None,
        },
        "cost_scenarios": costs,
        "all_cost_scenarios_passed": passed,
        "provenance": {
            "campaign_sha256": hashlib.sha256(
                json.dumps(campaign, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "bars_sha256": sha256_file(path),
        },
        "session_rows": sessions,
        "promotion_eligible": False,
        "llm_selector_eligible": False,
        "authority": {
            "automatic_approval": False,
            "automatic_paper_activation": False,
            "automatic_execution": False,
            "order_authority": False,
        },
    }
