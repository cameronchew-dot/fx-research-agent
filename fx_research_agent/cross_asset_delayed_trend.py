from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fx_research_agent.cross_asset_trend import (
    load_adjusted_prices,
    portfolio_rows,
    summarize,
    target_series,
)


STRATEGY_ID = "CROSS_ASSET_ETF_12M_TREND_ONE_MONTH_DELAY_V2"
FORWARD_START_DATE = "2026-12-01"
REPLICATION_TOLERANCES = {
    "average_monthly_excess_cash_return": 0.0005,
    "annualized_sharpe_zero_rate": 0.25,
    "maximum_log_drawdown": 0.02,
}


def _partition(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    first, second = int(len(rows) * 0.6), int(len(rows) * 0.8)
    return {
        "development": rows[:first],
        "chronological_oos": rows[first:second],
        "dated_confirmation": rows[second:],
    }


def _metric_difference(
    candidate: dict[str, Any],
    reference: dict[str, Any],
    metric: str,
) -> float | None:
    left, right = candidate.get(metric), reference.get(metric)
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _cross_source_replication(
    candidate: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    differences = {
        metric: _metric_difference(candidate, reference, metric)
        for metric in REPLICATION_TOLERANCES
    }
    gates = {
        "month_count_matches": candidate.get("month_count") == reference.get("month_count"),
        **{
            f"{metric}_within_tolerance": difference is not None
            and abs(difference) <= REPLICATION_TOLERANCES[metric]
            for metric, difference in differences.items()
        },
    }
    return {
        "candidate_dated_metrics": candidate,
        "v1_stale_control_reference": reference,
        "candidate_minus_reference": differences,
        "absolute_tolerances": REPLICATION_TOLERANCES,
        "gates": gates,
        "passed": all(gates.values()),
        "role": "MEASUREMENT_REPLICATION_ONLY_NOT_FRESH_CONFIRMATION",
    }


def _forward_gates(
    primary: dict[str, Any],
    controls: dict[str, dict[str, Any]],
) -> dict[str, bool]:
    enough = primary["month_count"] >= 36
    if not enough:
        return {
            "minimum_36_resolved_months": False,
            "average_excess_cash_positive": False,
            "information_ratio_at_least_point_five": False,
            "positive_year_rate_at_least_sixty_percent": False,
            "maximum_drawdown_within_twenty_five_percent": False,
            "excess_return_beats_immediate_opposite_and_random": False,
            "sharpe_and_drawdown_beat_buy_hold": False,
        }

    primary_excess = float(primary["average_monthly_excess_cash_return"])
    return {
        "minimum_36_resolved_months": True,
        "average_excess_cash_positive": primary_excess > 0,
        "information_ratio_at_least_point_five": float(primary["annualized_information_ratio_over_cash"] or 0) >= 0.5,
        "positive_year_rate_at_least_sixty_percent": float(primary["positive_year_rate"] or 0) >= 0.60,
        "maximum_drawdown_within_twenty_five_percent": float(primary["maximum_log_drawdown"] or -1) >= -0.25,
        "excess_return_beats_immediate_opposite_and_random": all(
            primary_excess > float(controls[name]["average_monthly_excess_cash_return"])
            for name in ("immediate", "opposite", "random")
        ),
        "sharpe_and_drawdown_beat_buy_hold": (
            float(primary["annualized_sharpe_zero_rate"] or 0)
            > float(controls["buy_hold"]["annualized_sharpe_zero_rate"] or 0)
            and float(primary["maximum_log_drawdown"] or -1)
            > float(controls["buy_hold"]["maximum_log_drawdown"] or -1)
        ),
    }


def evaluate_delayed(
    prices_path: Path,
    v1_result_path: Path,
    *,
    one_way_cost_bps: float = 10.0,
    forward_start: str = FORWARD_START_DATE,
) -> dict[str, Any]:
    days, panel = load_adjusted_prices(prices_path)
    targets = target_series(days, panel)
    delayed_rows = portfolio_rows(panel, targets, control="STALE", one_way_cost_bps=one_way_cost_bps)
    control_rows = {
        "immediate": portfolio_rows(panel, targets, control="PRIMARY", one_way_cost_bps=one_way_cost_bps),
        "opposite": portfolio_rows(panel, targets, control="OPPOSITE", one_way_cost_bps=one_way_cost_bps),
        "random": portfolio_rows(panel, targets, control="RANDOM", one_way_cost_bps=one_way_cost_bps),
        "buy_hold": portfolio_rows(panel, targets, control="BUY_HOLD", one_way_cost_bps=one_way_cost_bps),
    }

    partitions = _partition(delayed_rows)
    dated_candidate = summarize(partitions["dated_confirmation"])
    v1_result = json.loads(v1_result_path.read_text(encoding="utf-8"))
    reference = v1_result["controls_dated_confirmation"]["stale"]
    replication = _cross_source_replication(dated_candidate, reference)

    forward_rows = [row for row in delayed_rows if row["entry_date"] >= forward_start]
    forward_entry_dates = {row["entry_date"] for row in forward_rows}
    forward_controls = {
        name: summarize([row for row in rows if row["entry_date"] in forward_entry_dates])
        for name, rows in control_rows.items()
    }
    forward_metrics = summarize(forward_rows)
    gates = _forward_gates(forward_metrics, forward_controls)
    review_ready = gates["minimum_36_resolved_months"]

    if not replication["passed"]:
        status = "CROSS_SOURCE_REPLICATION_FAILED"
    elif not review_ready:
        status = "FORWARD_ACCUMULATION"
    elif all(gates.values()):
        status = "FORWARD_REVIEW_GATE_PASS_REQUIRES_HUMAN_REVIEW"
    else:
        status = "FORWARD_REVIEW_GATE_FAIL"

    return {
        "schema": "CROSS_ASSET_ETF_DELAYED_TREND_RESULT_V2",
        "strategy": STRATEGY_ID,
        "status": status,
        "source_role": "INDEPENDENT_CROSS_SOURCE_AND_FORWARD_EVIDENCE",
        "cost_model": {"one_way_cost_bps_per_unit_turnover": one_way_cost_bps},
        "forward_start": forward_start,
        "cross_source_replication": replication,
        "historical_replication_partitions": {
            name: summarize(rows) for name, rows in partitions.items()
        },
        "forward": {
            "metrics": forward_metrics,
            "controls": forward_controls,
            "gates": gates,
            "review_ready": review_ready,
            "rows": forward_rows,
        },
        "promotion_eligible": False,
        "authority": {
            "automatic_approval": False,
            "downstream_activation": False,
            "order_authority": False,
        },
    }


def _ledger_payload(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "decision_date",
        "entry_date",
        "exit_date",
        "net_return",
        "cash_return",
        "excess_cash_return",
        "risky_gross_weight",
        "cash_weight",
        "turnover",
        "cost_return",
        "active_assets",
    )
    return {key: row[key] for key in keys}


def append_forward_ledger(
    ledger_path: Path,
    rows: list[dict[str, Any]],
    *,
    source_sha256: str,
    recorded_at_utc: str | None = None,
) -> int:
    recorded = recorded_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    existing: dict[str, dict[str, Any]] = {}
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            existing[record["event_id"]] = record

    additions: list[dict[str, Any]] = []
    for row in rows:
        payload = _ledger_payload(row)
        identity = f"{STRATEGY_ID}:{row['decision_date']}:{row['entry_date']}:{row['exit_date']}"
        event_id = hashlib.sha256(identity.encode()).hexdigest()
        prior = existing.get(event_id)
        if prior:
            if prior["payload"] != payload:
                raise ValueError(f"conflicting immutable forward result: {event_id}")
            continue
        record = {
            "schema": "CROSS_ASSET_ETF_DELAYED_TREND_FORWARD_EVENT_V1",
            "event_id": event_id,
            "strategy": STRATEGY_ID,
            "known_at_utc": f"{row['exit_date']}T23:59:59Z",
            "recorded_at_utc": recorded,
            "first_seen_source_sha256": source_sha256,
            "payload": payload,
        }
        additions.append(record)
        existing[event_id] = record

    if additions:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as handle:
            for record in sorted(additions, key=lambda item: item["payload"]["entry_date"]):
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return len(additions)
