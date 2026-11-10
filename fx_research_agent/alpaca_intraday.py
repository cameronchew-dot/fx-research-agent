from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DATA_ENDPOINT = "https://data.alpaca.markets/v2/stocks/SPY/bars"
NEW_YORK = ZoneInfo("America/New_York")
CONTROL_NAMES = ("primary", "always", "opposite", "prior_day")
REQUIRED_TIMES = ("09:30", "09:59", "15:30", "15:55", "15:59")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def normalize_bar(raw: dict[str, Any]) -> dict[str, str]:
    timestamp = _utc(str(raw["t"]))
    values = {name: float(raw[key]) for name, key in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))}
    if any(not math.isfinite(value) or value <= 0 for value in values.values()):
        raise ValueError(f"invalid SPY price at {raw['t']}")
    if values["low"] > min(values["open"], values["close"]) or values["high"] < max(values["open"], values["close"]):
        raise ValueError(f"invalid SPY OHLC ordering at {raw['t']}")
    return {
        "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "symbol": "SPY",
        "open": format(values["open"], ".12g"),
        "high": format(values["high"], ".12g"),
        "low": format(values["low"], ".12g"),
        "close": format(values["close"], ".12g"),
        "volume": str(int(raw.get("v") or 0)),
        "trade_count": str(int(raw.get("n") or 0)),
        "vwap": format(float(raw.get("vw") or values["close"]), ".12g"),
        "feed": "SIP",
        "adjustment": "ALL",
    }


def extract_spy_minute_bars(
    output: Path,
    summary_path: Path,
    *,
    api_key_id: str,
    api_secret_key: str,
    start: str,
    end: str,
    pause_seconds: float = 0.05,
) -> dict[str, Any]:
    if not api_key_id or not api_secret_key:
        raise ValueError("Alpaca data credentials are required")
    public_parameters = {
        "timeframe": "1Min",
        "start": start,
        "end": end,
        "adjustment": "all",
        "feed": "sip",
        "sort": "asc",
        "limit": 10000,
    }
    headers = {
        "APCA-API-KEY-ID": api_key_id,
        "APCA-API-SECRET-KEY": api_secret_key,
        "Accept": "application/json",
        "User-Agent": "fx-research-agent/1 (market-data-only)",
    }
    rows_by_timestamp: dict[str, dict[str, str]] = {}
    page_token: str | None = None
    request_count = 0
    while True:
        parameters = dict(public_parameters)
        if page_token:
            parameters["page_token"] = page_token
        request = urllib.request.Request(
            f"{DATA_ENDPOINT}?{urllib.parse.urlencode(parameters)}",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.load(response)
        request_count += 1
        for raw in payload.get("bars") or []:
            row = normalize_bar(raw)
            timestamp = row["timestamp_utc"]
            prior = rows_by_timestamp.get(timestamp)
            if prior is not None and prior != row:
                raise ValueError(f"conflicting Alpaca bar rewrite: {timestamp}")
            rows_by_timestamp[timestamp] = row
        page_token = payload.get("next_page_token")
        if not page_token:
            break
        if pause_seconds:
            time.sleep(pause_seconds)

    rows = [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)]
    if not rows:
        raise ValueError("Alpaca returned no SPY minute bars")
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "schema": "ALPACA_SPY_SIP_MINUTE_EXPORT_V1",
        "source": "ALPACA_MARKET_DATA_API",
        "source_role": "HISTORICAL_RESEARCH_ONLY",
        "endpoint": DATA_ENDPOINT,
        "public_parameters": public_parameters,
        "symbol": "SPY",
        "row_count": len(rows),
        "timestamp_start_utc": rows[0]["timestamp_utc"],
        "timestamp_end_utc": rows[-1]["timestamp_utc"],
        "request_count": request_count,
        "output": str(output),
        "output_sha256": sha256_file(output),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "credentials_persisted": False,
        "promotion_eligible": False,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def load_minute_bars(path: Path) -> list[dict[str, Any]]:
    rows = []
    prior_timestamp: datetime | None = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw.get("symbol") != "SPY":
                raise ValueError("intraday campaign accepts SPY only")
            timestamp = _utc(raw["timestamp_utc"])
            if prior_timestamp is not None and timestamp <= prior_timestamp:
                raise ValueError("minute bars must be strictly increasing")
            prior_timestamp = timestamp
            if timestamp.astimezone(NEW_YORK).strftime("%H:%M") not in REQUIRED_TIMES:
                continue
            rows.append(
                {
                    "timestamp_utc": timestamp,
                    "open": float(raw["open"]),
                    "high": float(raw["high"]),
                    "low": float(raw["low"]),
                    "close": float(raw["close"]),
                }
            )
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
        if "09:30" <= clock <= "15:59":
            if clock in sessions[day]:
                raise ValueError(f"duplicate SPY regular-session minute: {day} {clock}")
            sessions[day][clock] = row

    output = []
    previous_close: float | None = None
    previous_morning_return: float | None = None
    for day in sorted(sessions):
        bars = sessions[day]
        complete = all(clock in bars for clock in REQUIRED_TIMES)
        current_morning_return: float | None = None
        if complete and previous_close is not None:
            morning_return = bars["09:59"]["close"] / previous_close - 1.0
            current_morning_return = morning_return
            execution_return = bars["15:55"]["open"] / bars["15:30"]["open"] - 1.0
            output.append(
                {
                    "date": day,
                    "morning_return": morning_return,
                    "execution_gross_return": execution_return,
                    "primary_active": morning_return > 0.0,
                    "always_active": True,
                    "opposite_active": morning_return <= 0.0,
                    "prior_day_active": previous_morning_return is not None and previous_morning_return > 0.0,
                }
            )
        if complete:
            previous_close = bars["15:59"]["close"]
            previous_morning_return = current_morning_return
    return output


def strategy_daily_return(row: dict[str, Any], control: str, one_way_cost_bps: float) -> float:
    if not row[f"{control}_active"]:
        return 0.0
    return float(row["execution_gross_return"]) - 2.0 * one_way_cost_bps / 10000.0


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


def _compound(returns: list[float]) -> float:
    value = 1.0
    for result in returns:
        value *= 1.0 + result
    return value - 1.0


def summarize(rows: list[dict[str, Any]], control: str, one_way_cost_bps: float) -> dict[str, Any]:
    daily = [strategy_daily_return(row, control, one_way_cost_bps) for row in rows]
    trades = [value for row, value in zip(rows, daily) if row[f"{control}_active"]]
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
        "trade_frequency": len(trades) / len(rows) if rows else None,
        "positive_trade_rate": sum(value > 0 for value in trades) / len(trades) if trades else None,
        "average_gross_return_per_trade": statistics.fmean(
            row["execution_gross_return"] for row in rows if row[f"{control}_active"]
        ) if trades else None,
        "average_net_return_per_trade": statistics.fmean(trades) if trades else None,
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
        covariance = sum(centered[index] * centered[index - offset] for index in range(offset, count)) / count
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
    combined_metrics = {
        control: summarize(validation_plus_dated, control, one_way_cost_bps)
        for control in CONTROL_NAMES
    }
    primary_returns = [strategy_daily_return(row, "primary", one_way_cost_bps) for row in validation_plus_dated]
    paired_t_stats = {}
    for control in ("always", "opposite", "prior_day"):
        comparator = [strategy_daily_return(row, control, one_way_cost_bps) for row in validation_plus_dated]
        paired_t_stats[control] = newey_west_t_stat(
            [left - right for left, right in zip(primary_returns, comparator)]
        )
    gates = campaign["review_gates"]
    sample_gates = {
        name: metrics[name]["primary"]["trade_count"] >= minimum
        for name, minimum in gates["minimum_primary_trades"].items()
    }
    checks = {
        **{f"minimum_primary_trades_{name}": value for name, value in sample_gates.items()},
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
            combined_metrics["primary"]["positive_month_rate"] is not None
            and combined_metrics["primary"]["positive_month_rate"]
            >= float(gates["validation_plus_dated_positive_month_rate_minimum"])
        ),
        "validation_plus_dated_drawdown": (
            combined_metrics["primary"]["maximum_drawdown"] is not None
            and combined_metrics["primary"]["maximum_drawdown"]
            >= float(gates["validation_plus_dated_maximum_drawdown_floor"])
        ),
        "validation_plus_dated_beats_all_controls": all(
            combined_metrics["primary"]["average_daily_net_return"]
            > combined_metrics[control]["average_daily_net_return"]
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
        "validation_plus_dated": combined_metrics,
        "paired_newey_west_t_stats": paired_t_stats,
        "gates": checks,
        "passed": all(checks.values()),
    }


def evaluate(path: Path, campaign: dict[str, Any]) -> dict[str, Any]:
    minute_rows = load_minute_bars(path)
    population = campaign["population"]
    sessions = build_session_rows(
        minute_rows,
        start_date=population["window_start"],
        end_date=population["window_end_inclusive"],
    )
    exact = campaign["exact_specification"]
    costs = {
        "primary": _cost_evaluation(sessions, campaign, float(exact["primary_one_way_cost_bps"])),
        "stress": _cost_evaluation(sessions, campaign, float(exact["stress_one_way_cost_bps"])),
    }
    passed = all(result["passed"] for result in costs.values())
    return {
        "schema": "SPY_MORNING_MOMENTUM_LAST_HALF_HOUR_RESULT_V1",
        "campaign_id": campaign["campaign_id"],
        "status": (
            "HISTORICAL_GATE_PASS_REQUIRES_FRESH_PAPER_FORWARD_REVIEW"
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
        "authority": {
            "automatic_approval": False,
            "automatic_paper_activation": False,
            "automatic_execution": False,
            "order_authority": False,
        },
    }
