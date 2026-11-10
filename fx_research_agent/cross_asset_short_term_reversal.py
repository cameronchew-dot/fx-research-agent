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


DATA_ENDPOINT_TEMPLATE = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
RISKY_SYMBOLS = ("SPY", "EFA", "IEF", "TLT", "GLD", "DBC", "UUP")
CASH_SYMBOL = "BIL"
ALL_SYMBOLS = (*RISKY_SYMBOLS, CASH_SYMBOL)
CONTROL_NAMES = ("primary", "winner", "random", "spy")
CAMPAIGN_ID = "CAMPAIGN_CROSS_ASSET_SHORT_TERM_REVERSAL_V1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def normalize_daily_bar(symbol: str, raw: dict[str, Any]) -> dict[str, str]:
    timestamp = _utc(str(raw["t"]))
    values = {
        name: float(raw[key])
        for name, key in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))
    }
    if any(not math.isfinite(value) or value <= 0 for value in values.values()):
        raise ValueError(f"invalid {symbol} price at {raw['t']}")
    if values["low"] > min(values["open"], values["close"]):
        raise ValueError(f"invalid {symbol} daily low at {raw['t']}")
    if values["high"] < max(values["open"], values["close"]):
        raise ValueError(f"invalid {symbol} daily high at {raw['t']}")
    return {
        "date": timestamp.date().isoformat(),
        "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "symbol": symbol,
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


def extract_daily_bars(
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
        "timeframe": "1Day",
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
    rows_by_identity: dict[tuple[str, str], dict[str, str]] = {}
    request_count = 0
    for symbol in ALL_SYMBOLS:
        page_token: str | None = None
        while True:
            parameters = dict(public_parameters)
            if page_token:
                parameters["page_token"] = page_token
            request = urllib.request.Request(
                f"{DATA_ENDPOINT_TEMPLATE.format(symbol=symbol)}?{urllib.parse.urlencode(parameters)}",
                headers=headers,
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.load(response)
            request_count += 1
            for raw in payload.get("bars") or []:
                row = normalize_daily_bar(symbol, raw)
                identity = (row["date"], symbol)
                prior = rows_by_identity.get(identity)
                if prior is not None and prior != row:
                    raise ValueError(f"conflicting Alpaca daily bar rewrite: {identity}")
                rows_by_identity[identity] = row
            page_token = payload.get("next_page_token")
            if not page_token:
                break
            if pause_seconds:
                time.sleep(pause_seconds)

    rows = [rows_by_identity[key] for key in sorted(rows_by_identity)]
    if not rows:
        raise ValueError("Alpaca returned no cross-asset daily bars")
    counts = {symbol: sum(row["symbol"] == symbol for row in rows) for symbol in ALL_SYMBOLS}
    if any(count == 0 for count in counts.values()):
        raise ValueError(f"missing Alpaca symbols: {counts}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "schema": "ALPACA_CROSS_ASSET_SIP_DAILY_EXPORT_V1",
        "source": "ALPACA_MARKET_DATA_API",
        "source_role": "HISTORICAL_RESEARCH_ONLY",
        "endpoint_template": DATA_ENDPOINT_TEMPLATE,
        "public_parameters": public_parameters,
        "symbols": list(ALL_SYMBOLS),
        "row_count": len(rows),
        "rows_by_symbol": counts,
        "date_start": min(row["date"] for row in rows),
        "date_end": max(row["date"] for row in rows),
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


def load_daily_panel(path: Path) -> tuple[list[str], dict[str, dict[str, dict[str, float]]]]:
    by_date: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            symbol = raw["symbol"]
            if symbol not in ALL_SYMBOLS:
                continue
            day = raw["date"]
            values = {field: float(raw[field]) for field in ("open", "high", "low", "close")}
            if any(not math.isfinite(value) or value <= 0 for value in values.values()):
                raise ValueError(f"invalid daily price: {day} {symbol}")
            if symbol in by_date[day]:
                raise ValueError(f"duplicate daily bar: {day} {symbol}")
            by_date[day][symbol] = values
    common_dates = sorted(day for day, panel in by_date.items() if set(panel) == set(ALL_SYMBOLS))
    if len(common_dates) < 30:
        raise ValueError("insufficient complete cross-asset daily history")
    return common_dates, {day: by_date[day] for day in common_dates}


def _fixed_random_symbol(decision_date: str) -> str:
    digest = hashlib.sha256(f"{CAMPAIGN_ID}:{decision_date}".encode()).digest()
    return RISKY_SYMBOLS[int.from_bytes(digest[:8], "big") % len(RISKY_SYMBOLS)]


def build_events(
    dates: list[str],
    panel: dict[str, dict[str, dict[str, float]]],
    *,
    lookback_sessions: int,
    volatility_sessions: int,
    trigger_z: float,
    holding_sessions: int,
) -> list[dict[str, Any]]:
    closes = {
        symbol: [panel[day][symbol]["close"] for day in dates]
        for symbol in ALL_SYMBOLS
    }
    daily_returns = {
        symbol: [None] + [closes[symbol][index] / closes[symbol][index - 1] - 1.0 for index in range(1, len(dates))]
        for symbol in ALL_SYMBOLS
    }
    events: list[dict[str, Any]] = []
    next_allowed_decision_index = max(lookback_sessions, volatility_sessions + 1)
    last_possible = len(dates) - holding_sessions - 1
    for index in range(max(lookback_sessions, volatility_sessions + 1), last_possible + 1):
        if index < next_allowed_decision_index:
            continue
        z_scores: dict[str, float] = {}
        for symbol in RISKY_SYMBOLS:
            prior_returns = daily_returns[symbol][index - volatility_sessions:index]
            if any(value is None for value in prior_returns):
                break
            volatility = statistics.stdev(float(value) for value in prior_returns)
            if volatility <= 0:
                break
            trailing_return = closes[symbol][index] / closes[symbol][index - lookback_sessions] - 1.0
            z_scores[symbol] = trailing_return / (volatility * math.sqrt(lookback_sessions))
        if len(z_scores) != len(RISKY_SYMBOLS):
            continue
        primary_symbol = min(z_scores, key=lambda symbol: (z_scores[symbol], symbol))
        if z_scores[primary_symbol] > trigger_z:
            continue
        winner_symbol = max(z_scores, key=lambda symbol: (z_scores[symbol], symbol))
        random_symbol = _fixed_random_symbol(dates[index])
        entry_index = index + 1
        exit_index = index + holding_sessions
        selections = {
            "primary": primary_symbol,
            "winner": winner_symbol,
            "random": random_symbol,
            "spy": "SPY",
        }
        gross_returns = {
            name: panel[dates[exit_index]][symbol]["close"] / panel[dates[entry_index]][symbol]["open"] - 1.0
            for name, symbol in selections.items()
        }
        bil_return = (
            panel[dates[exit_index]][CASH_SYMBOL]["close"]
            / panel[dates[entry_index]][CASH_SYMBOL]["open"]
            - 1.0
        )
        events.append(
            {
                "decision_date": dates[index],
                "entry_date": dates[entry_index],
                "exit_date": dates[exit_index],
                "primary_symbol": primary_symbol,
                "winner_symbol": winner_symbol,
                "random_symbol": random_symbol,
                "primary_z": z_scores[primary_symbol],
                "winner_z": z_scores[winner_symbol],
                "bil_gross_return": bil_return,
                "selections": selections,
                "gross_returns": gross_returns,
            }
        )
        next_allowed_decision_index = exit_index
    return events


def event_return(event: dict[str, Any], control: str, one_way_cost_bps: float) -> float:
    return float(event["gross_returns"][control]) - 2.0 * one_way_cost_bps / 10000.0


def _compound(values: list[float]) -> float:
    equity = 1.0
    for value in values:
        equity *= 1.0 + value
    return equity - 1.0


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


def t_stat(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    standard_deviation = statistics.stdev(values)
    if standard_deviation <= 0:
        return None
    return statistics.fmean(values) / (standard_deviation / math.sqrt(len(values)))


def summarize(events: list[dict[str, Any]], control: str, one_way_cost_bps: float) -> dict[str, Any]:
    net = [event_return(event, control, one_way_cost_bps) for event in events]
    excess_bil = [value - float(event["bil_gross_return"]) for event, value in zip(events, net)]
    holding_days = (
        (datetime.fromisoformat(events[-1]["exit_date"]) - datetime.fromisoformat(events[0]["entry_date"])).days
        if len(events) > 1 else None
    )
    return {
        "event_count": len(events),
        "events_per_week": (len(events) / holding_days * 7.0) if holding_days and holding_days > 0 else None,
        "positive_net_return_rate": sum(value > 0 for value in net) / len(net) if net else None,
        "average_gross_return": statistics.fmean(event["gross_returns"][control] for event in events) if events else None,
        "average_net_return": statistics.fmean(net) if net else None,
        "median_net_return": statistics.median(net) if net else None,
        "average_excess_bil_return": statistics.fmean(excess_bil) if excess_bil else None,
        "excess_bil_t_stat": t_stat(excess_bil),
        "compounded_net_return": _compound(net),
        "maximum_drawdown": _maximum_drawdown(net),
    }


def _partition(events: list[dict[str, Any]], bounds: list[str]) -> list[dict[str, Any]]:
    return [event for event in events if bounds[0] <= event["decision_date"] <= bounds[1]]


def _cost_evaluation(
    events: list[dict[str, Any]],
    campaign: dict[str, Any],
    one_way_cost_bps: float,
) -> dict[str, Any]:
    partitions = {name: _partition(events, bounds) for name, bounds in campaign["partitions"].items()}
    combined = [
        event for event in events
        if campaign["partitions"]["chronological_validation"][0]
        <= event["decision_date"]
        <= campaign["partitions"]["dated_confirmation"][1]
    ]
    metrics = {
        name: {control: summarize(rows, control, one_way_cost_bps) for control in CONTROL_NAMES}
        for name, rows in partitions.items()
    }
    combined_metrics = {control: summarize(combined, control, one_way_cost_bps) for control in CONTROL_NAMES}
    primary_returns = [event_return(event, "primary", one_way_cost_bps) for event in combined]
    paired_t_stats = {
        control: t_stat([
            left - event_return(event, control, one_way_cost_bps)
            for event, left in zip(combined, primary_returns)
        ])
        for control in ("winner", "random", "spy")
    }
    gates = campaign["review_gates"]
    checks = {
        **{
            f"minimum_events_{name}": metrics[name]["primary"]["event_count"] >= minimum
            for name, minimum in gates["minimum_events"].items()
        },
        "positive_excess_bil_all_partitions": all(
            metrics[name]["primary"]["average_excess_bil_return"] is not None
            and metrics[name]["primary"]["average_excess_bil_return"] > 0
            for name in campaign["partitions"]
        ),
        "validation_and_dated_positive_net_return": all(
            metrics[name]["primary"]["average_net_return"] is not None
            and metrics[name]["primary"]["average_net_return"] > 0
            for name in ("chronological_validation", "dated_confirmation")
        ),
        "validation_plus_dated_positive_rate": (
            combined_metrics["primary"]["positive_net_return_rate"] is not None
            and combined_metrics["primary"]["positive_net_return_rate"]
            >= float(gates["validation_plus_dated_positive_event_rate_minimum"])
        ),
        "validation_plus_dated_drawdown": (
            combined_metrics["primary"]["maximum_drawdown"] is not None
            and combined_metrics["primary"]["maximum_drawdown"]
            >= float(gates["validation_plus_dated_maximum_drawdown_floor"])
        ),
        "validation_plus_dated_beats_all_controls": all(
            combined_metrics["primary"]["average_net_return"] is not None
            and combined_metrics[control]["average_net_return"] is not None
            and combined_metrics["primary"]["average_net_return"]
            > combined_metrics[control]["average_net_return"]
            for control in ("winner", "random", "spy")
        ),
        "validation_plus_dated_excess_bil_t_stat": (
            combined_metrics["primary"]["excess_bil_t_stat"] is not None
            and combined_metrics["primary"]["excess_bil_t_stat"]
            >= float(gates["validation_plus_dated_t_stat_minimum"])
        ),
        "validation_plus_dated_paired_t_stats": all(
            value is not None and value >= float(gates["validation_plus_dated_t_stat_minimum"])
            for value in paired_t_stats.values()
        ),
    }
    return {
        "one_way_cost_bps": one_way_cost_bps,
        "partitions": metrics,
        "validation_plus_dated": combined_metrics,
        "paired_t_stats": paired_t_stats,
        "gates": checks,
        "passed": all(checks.values()),
    }


def evaluate(path: Path, campaign: dict[str, Any]) -> dict[str, Any]:
    dates, panel = load_daily_panel(path)
    exact = campaign["exact_specification"]
    events = build_events(
        dates,
        panel,
        lookback_sessions=int(exact["return_lookback_sessions"]),
        volatility_sessions=int(exact["prior_volatility_sessions"]),
        trigger_z=float(exact["primary_trigger_z_at_or_below"]),
        holding_sessions=int(exact["holding_sessions"]),
    )
    costs = {
        "primary": _cost_evaluation(events, campaign, float(exact["primary_one_way_cost_bps"])),
        "stress": _cost_evaluation(events, campaign, float(exact["stress_one_way_cost_bps"])),
    }
    passed = all(result["passed"] for result in costs.values())
    return {
        "schema": "CROSS_ASSET_SHORT_TERM_REVERSAL_RESULT_V1",
        "campaign_id": campaign["campaign_id"],
        "status": "HISTORICAL_GATE_PASS_REQUIRES_HUMAN_REVIEW" if passed else "HISTORICAL_GATE_FAIL",
        "population": {
            "complete_session_count": len(dates),
            "session_start": dates[0],
            "session_end": dates[-1],
            "event_count": len(events),
        },
        "cost_scenarios": costs,
        "all_cost_scenarios_passed": passed,
        "provenance": {
            "campaign_sha256": hashlib.sha256(
                json.dumps(campaign, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "bars_sha256": sha256_file(path),
        },
        "event_rows": events,
        "promotion_eligible": False,
        "authority": {
            "automatic_approval": False,
            "automatic_paper_activation": False,
            "automatic_execution": False,
            "order_authority": False,
        },
    }
