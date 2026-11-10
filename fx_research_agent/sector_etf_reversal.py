from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
REQUIRED_TIMES = ("09:30", "09:45", "10:15", "15:45")
CONTROL_NAMES = ("primary", "winner", "random", "equal_weight", "spy")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def load_required_bars(path: Path, *, expected_symbol: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prior_timestamp: datetime | None = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw.get("symbol") != expected_symbol:
                raise ValueError(f"expected {expected_symbol}, found {raw.get('symbol')}")
            timestamp = _utc(raw["timestamp_utc"])
            if prior_timestamp is not None and timestamp <= prior_timestamp:
                raise ValueError(f"{expected_symbol} bars must be strictly increasing")
            prior_timestamp = timestamp
            local = timestamp.astimezone(NEW_YORK)
            if local.strftime("%H:%M") not in REQUIRED_TIMES:
                continue
            values = {key: float(raw[key]) for key in ("open", "high", "low", "close")}
            if any(not math.isfinite(value) or value <= 0 for value in values.values()):
                raise ValueError(f"invalid {expected_symbol} price at {raw['timestamp_utc']}")
            if values["low"] > min(values["open"], values["close"]):
                raise ValueError(f"invalid {expected_symbol} low at {raw['timestamp_utc']}")
            if values["high"] < max(values["open"], values["close"]):
                raise ValueError(f"invalid {expected_symbol} high at {raw['timestamp_utc']}")
            rows.append({"timestamp_utc": timestamp, **values})
    return rows


def _complete_sessions(
    rows: list[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
    symbol: str,
) -> dict[str, dict[str, dict[str, Any]]]:
    sessions: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        local = row["timestamp_utc"].astimezone(NEW_YORK)
        day = local.date().isoformat()
        if day < start_date or day > end_date or local.weekday() >= 5:
            continue
        clock = local.strftime("%H:%M")
        if clock in sessions[day]:
            raise ValueError(f"duplicate {symbol} regular-session bar: {day} {clock}")
        sessions[day][clock] = row
    return {
        day: bars
        for day, bars in sessions.items()
        if all(clock in bars for clock in REQUIRED_TIMES)
    }


def _fixed_hash_symbol(campaign_id: str, day: str, symbols: tuple[str, ...]) -> str:
    digest = hashlib.sha256(f"{campaign_id}:{day}".encode()).digest()
    return symbols[int.from_bytes(digest[:8], "big") % len(symbols)]


def build_session_rows(
    panel_rows: dict[str, list[dict[str, Any]]],
    *,
    sector_universe: tuple[str, ...],
    market_control: str,
    campaign_id: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    expected = set(sector_universe) | {market_control}
    if set(panel_rows) != expected:
        raise ValueError("panel symbols do not match the frozen universe")
    sessions = {
        symbol: _complete_sessions(
            rows,
            start_date=start_date,
            end_date=end_date,
            symbol=symbol,
        )
        for symbol, rows in panel_rows.items()
    }
    common_dates = sorted(set.intersection(*(set(by_day) for by_day in sessions.values())))
    prior_closes: dict[str, float] | None = None
    output: list[dict[str, Any]] = []
    for day in common_dates:
        if prior_closes is not None:
            overnight = {
                symbol: float(sessions[symbol][day]["09:30"]["open"]) / prior_closes[symbol] - 1.0
                for symbol in sector_universe
            }
            selected = min(sector_universe, key=lambda symbol: (overnight[symbol], symbol))
            winner = max(sector_universe, key=lambda symbol: (overnight[symbol], symbol))
            random_symbol = _fixed_hash_symbol(campaign_id, day, sector_universe)
            execution = {
                symbol: (
                    float(sessions[symbol][day]["10:15"]["close"])
                    / float(sessions[symbol][day]["09:45"]["open"])
                    - 1.0
                )
                for symbol in expected
            }
            active = overnight[selected] < 0.0
            output.append(
                {
                    "date": day,
                    "primary_active": active,
                    "selected_symbol": selected,
                    "winner_symbol": winner,
                    "random_symbol": random_symbol,
                    "selected_overnight_return": overnight[selected],
                    "cross_section_overnight_dispersion": statistics.pstdev(overnight.values()),
                    "overnight_returns": {symbol: overnight[symbol] for symbol in sector_universe},
                    "primary_gross_return": execution[selected],
                    "winner_gross_return": execution[winner],
                    "random_gross_return": execution[random_symbol],
                    "equal_weight_gross_return": statistics.fmean(execution[symbol] for symbol in sector_universe),
                    "spy_gross_return": execution[market_control],
                }
            )
        prior_closes = {
            symbol: float(sessions[symbol][day]["15:45"]["close"])
            for symbol in expected
        }
    return output


def strategy_daily_return(row: dict[str, Any], control: str, one_way_cost_bps: float) -> float:
    if not row["primary_active"]:
        return 0.0
    return float(row[f"{control}_gross_return"]) - 2.0 * one_way_cost_bps / 10000.0


def _compound(values: list[float]) -> float:
    total = 1.0
    for value in values:
        total *= 1.0 + value
    return total - 1.0


def _maximum_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    equity = peak = 1.0
    worst = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


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


def summarize(rows: list[dict[str, Any]], control: str, one_way_cost_bps: float) -> dict[str, Any]:
    daily = [strategy_daily_return(row, control, one_way_cost_bps) for row in rows]
    active_rows = [row for row in rows if row["primary_active"]]
    trades = [strategy_daily_return(row, control, one_way_cost_bps) for row in active_rows]
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
        "common_session_count": len(rows),
        "event_count": len(trades),
        "events_per_week": len(trades) / len(rows) * 5.0 if rows else None,
        "average_gross_return_per_event": statistics.fmean(
            float(row[f"{control}_gross_return"]) for row in active_rows
        ) if active_rows else None,
        "average_net_return_per_event": statistics.fmean(trades) if trades else None,
        "median_net_return_per_event": statistics.median(trades) if trades else None,
        "positive_event_rate": sum(value > 0 for value in trades) / len(trades) if trades else None,
        "average_daily_net_return": mean_daily,
        "annualized_sharpe": (
            mean_daily / daily_std * math.sqrt(252)
            if mean_daily is not None and daily_std is not None and daily_std > 0
            else None
        ),
        "newey_west_t_stat": newey_west_t_stat(daily),
        "positive_month_rate": sum(value > 0 for value in month_returns) / len(month_returns) if month_returns else None,
        "month_count": len(month_returns),
        "compounded_return": _compound(daily),
        "maximum_drawdown": _maximum_drawdown(daily),
        "worst_calendar_year_return": min(year_returns) if year_returns else None,
        "selection_counts_by_sector": dict(sorted(Counter(
            row["selected_symbol"] for row in active_rows
        ).items())) if control == "primary" else None,
    }


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
    primary_daily = [
        strategy_daily_return(row, "primary", one_way_cost_bps)
        for row in validation_plus_dated
    ]
    paired_t_stats = {}
    for control in ("winner", "random", "equal_weight", "spy"):
        comparator = [
            strategy_daily_return(row, control, one_way_cost_bps)
            for row in validation_plus_dated
        ]
        paired_t_stats[control] = newey_west_t_stat(
            [left - right for left, right in zip(primary_daily, comparator)]
        )

    gates = campaign["review_gates"]
    checks = {
        **{
            f"minimum_primary_events_{name}":
            metrics[name]["primary"]["event_count"] >= minimum
            for name, minimum in gates["minimum_primary_events"].items()
        },
        "average_net_positive_all_partitions": all(
            metrics[name]["primary"]["average_net_return_per_event"] is not None
            and metrics[name]["primary"]["average_net_return_per_event"] > 0
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
            for control in ("winner", "random", "equal_weight", "spy")
        ),
        "validation_plus_dated_primary_newey_west_t_stat": (
            combined["primary"]["newey_west_t_stat"] is not None
            and combined["primary"]["newey_west_t_stat"]
            >= float(gates["validation_plus_dated_primary_newey_west_t_stat_minimum"])
        ),
        "validation_plus_dated_paired_newey_west_t_stats": all(
            value is not None
            and value >= float(gates["validation_plus_dated_paired_newey_west_t_stat_minimum"])
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


def evaluate(paths: dict[str, Path], campaign: dict[str, Any]) -> dict[str, Any]:
    population = campaign["population"]
    sector_universe = tuple(population["sector_universe"])
    market_control = str(population["market_control"])
    expected = set(sector_universe) | {market_control}
    if set(paths) != expected:
        raise ValueError("source paths do not match the frozen panel")
    panel = {
        symbol: load_required_bars(path, expected_symbol=symbol)
        for symbol, path in paths.items()
    }
    rows = build_session_rows(
        panel,
        sector_universe=sector_universe,
        market_control=market_control,
        campaign_id=campaign["campaign_id"],
        start_date=population["window_start"],
        end_date=population["window_end_inclusive"],
    )
    exact = campaign["exact_specification"]
    costs = {
        "primary": _cost_evaluation(rows, campaign, float(exact["primary_one_way_cost_bps"])),
        "stress": _cost_evaluation(rows, campaign, float(exact["stress_one_way_cost_bps"])),
    }
    passed = all(result["passed"] for result in costs.values())
    return {
        "schema": "SECTOR_ETF_CROSS_SECTIONAL_OVERNIGHT_REVERSAL_RESULT_V1",
        "campaign_id": campaign["campaign_id"],
        "status": (
            "HISTORICAL_GATE_PASS_REQUIRES_FRESH_FORWARD_REVIEW"
            if passed
            else "HISTORICAL_GATE_FAIL"
        ),
        "population": {
            "common_session_count": len(rows),
            "session_start": rows[0]["date"] if rows else None,
            "session_end": rows[-1]["date"] if rows else None,
            "required_bar_counts": {symbol: len(panel[symbol]) for symbol in sorted(panel)},
        },
        "cost_scenarios": costs,
        "all_cost_scenarios_passed": passed,
        "provenance": {
            "campaign_sha256": hashlib.sha256(
                json.dumps(campaign, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "bars_sha256": {symbol: sha256_file(paths[symbol]) for symbol in sorted(paths)},
        },
        "session_rows": rows,
        "promotion_eligible": False,
        "llm_forward_shadow_eligible": passed,
        "authority": {
            "automatic_approval": False,
            "automatic_paper_activation": False,
            "automatic_execution": False,
            "order_authority": False,
        },
    }
