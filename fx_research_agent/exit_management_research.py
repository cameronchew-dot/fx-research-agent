from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .experiments import _load_evidence
from .market_data import resolve_payload_path, validate_manifest
from .regime_enrichment import _load_payload, _manifest_path, parse_utc
from .signal_context_forensics import (
    PIP_SIZE_BY_INSTRUMENT,
    _apply_benjamini_hochberg,
    _candidate_strategy_facts,
    _signal_id,
)
from .storage import canonical_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _paired_sign_p_value(differences: list[float]) -> float:
    better = sum(value > 1e-9 for value in differences)
    worse = sum(value < -1e-9 for value in differences)
    count = better + worse
    if count == 0:
        return 1.0
    tail = sum(math.comb(count, value) for value in range(min(better, worse) + 1))
    return min(1.0, 2.0 * tail / (2**count))


def _summary(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "positive_count": sum(value > 0 for value in values),
        "positive_rate": (
            round(sum(value > 0 for value in values) / len(values), 6)
            if values
            else None
        ),
        "average_net_r": round(statistics.fmean(values), 6) if values else None,
        "median_net_r": round(statistics.median(values), 6) if values else None,
        "worst_net_r": round(min(values), 6) if values else None,
    }


def _simulate_policy(
    candles: list[dict[str, Any]],
    *,
    direction: str,
    entry: float,
    risk_distance: float,
    spread_r: float,
    policy: str,
) -> dict[str, Any]:
    if direction not in {"LONG", "SHORT"} or risk_distance <= 0:
        raise ValueError("valid direction and positive risk distance are required")
    partial = policy in {"PARTIAL_1R_RUNNER_2R", "PARTIAL_1R_BE_RUNNER_2R"}
    break_even = policy in {"BREAK_EVEN_AFTER_1R", "PARTIAL_1R_BE_RUNNER_2R"}
    target_r = 2.0 if partial else 1.5
    remaining = 1.0
    realized = 0.0
    partial_taken = False
    break_even_active = False
    exit_reason = "HORIZON"
    exit_index = len(candles) - 1
    extra_partial_cost_r = 0.0

    def levels(candle: dict[str, Any]) -> tuple[float, float]:
        high = float(candle["high"])
        low = float(candle["low"])
        if direction == "LONG":
            return (high - entry) / risk_distance, (entry - low) / risk_distance
        return (entry - low) / risk_distance, (high - entry) / risk_distance

    for index, candle in enumerate(candles):
        favorable, adverse = levels(candle)
        stop_r = 0.0 if break_even_active else -1.0
        stop_hit = adverse >= abs(stop_r) if stop_r < 0 else (
            float(candle["low"]) <= entry
            if direction == "LONG"
            else float(candle["high"]) >= entry
        )
        target_hit = favorable >= target_r
        activation_hit = favorable >= 1.0

        # Stop-first is deliberately conservative whenever intrabar ordering is
        # unknowable, including a bar that first qualifies a management change.
        if stop_hit:
            realized += remaining * stop_r
            remaining = 0.0
            exit_reason = (
                "BREAK_EVEN"
                if stop_r == 0.0
                else "STOP_FIRST_CONSERVATIVE_TIE"
                if target_hit or (activation_hit and not partial_taken)
                else "STOP"
            )
            exit_index = index
            break

        if partial and not partial_taken and activation_hit:
            partial_fraction = 0.5
            extra_partial_cost_r = partial_fraction * spread_r / 2.0
            realized += partial_fraction * 1.0 - extra_partial_cost_r
            remaining -= partial_fraction
            partial_taken = True

        if target_hit:
            realized += remaining * target_r
            remaining = 0.0
            exit_reason = "TARGET"
            exit_index = index
            break

        # Activation is effective on the next candle, never retroactively on
        # the candle whose high or low first crossed +1R.
        if break_even and activation_hit:
            break_even_active = True

    if remaining > 0:
        close = float(candles[-1]["close"])
        exit_price = (
            close - spread_r * risk_distance / 2.0
            if direction == "LONG"
            else close + spread_r * risk_distance / 2.0
        )
        close_r = (
            (exit_price - entry) / risk_distance
            if direction == "LONG"
            else (entry - exit_price) / risk_distance
        )
        realized += remaining * close_r

    return {
        "policy": policy,
        "net_r": round(realized, 8),
        "exit_reason": exit_reason,
        "exit_bar_index": exit_index,
        "partial_taken": partial_taken,
        "break_even_activated": break_even_active,
        "extra_partial_cost_r": round(extra_partial_cost_r, 8),
    }


def _load_m15_candles(
    connection,
    market_inbox: Path,
    instrument: str,
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    candles: dict[str, dict[str, Any]] = {}
    manifests: list[str] = []
    for row in connection.execute(
        "SELECT payload_json FROM market_data_manifests "
        "WHERE usable_for_testing=1 ORDER BY registered_at_utc, manifest_id"
    ).fetchall():
        registered = json.loads(row["payload_json"])
        if registered.get("instrument") != instrument:
            continue
        if not set(registered.get("data_classes") or []).intersection(
            {"COMPLETED_CANDLES", "HISTORICAL_COMPLETED_CANDLES"}
        ):
            continue
        if parse_utc(str(registered["window_start_utc"])) > end or parse_utc(
            str(registered["window_end_utc"])
        ) < start:
            continue
        manifest_id = str(registered["manifest_id"])
        manifest_path = _manifest_path(market_inbox, manifest_id)
        manifest = validate_manifest(manifest_path)
        if manifest != registered:
            raise ValueError(f"registered market manifest differs: {manifest_id}")
        payload = _load_payload(resolve_payload_path(manifest_path, manifest))
        used = False
        for candle in payload.get("completed_candles") or []:
            if candle.get("instrument") != instrument or candle.get("granularity") != "M15":
                continue
            end_text = str(
                candle.get("candle_end_time_utc")
                or candle.get("end_time_utc")
                or ""
            )
            if not end_text:
                continue
            candle_end = parse_utc(end_text)
            candle_start = parse_utc(
                str(candle.get("candle_time_utc") or candle.get("time_utc"))
            ) if candle.get("candle_time_utc") or candle.get("time_utc") else candle_end - timedelta(minutes=15)
            if candle_end < start or candle_start > end:
                continue
            core = {
                "start_time_utc": candle_start.isoformat().replace("+00:00", "Z"),
                "end_time_utc": candle_end.isoformat().replace("+00:00", "Z"),
                "open": candle.get("open"),
                "high": candle.get("high"),
                "low": candle.get("low"),
                "close": candle.get("close"),
            }
            existing = candles.get(core["start_time_utc"])
            if existing is not None and canonical_json(existing) != canonical_json(core):
                raise ValueError(
                    f"conflicting immutable M15 candle: {core['start_time_utc']}"
                )
            candles[core["start_time_utc"]] = core
            used = True
        if used:
            manifests.append(manifest_id)
    return [candles[key] for key in sorted(candles)], manifests


def _population_rows(
    events: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    instrument: str,
) -> list[dict[str, Any]]:
    outcome_by_event = {str(row.get("event_id")): row for row in outcomes}
    candidates = []
    for event in events:
        if event.get("instrument") != instrument:
            continue
        outcome = outcome_by_event.get(str(event.get("event_id")))
        if not outcome:
            continue
        if (
            outcome.get("entry_model") != "NEXT_M15_OPEN_WITH_DECISION_SPREAD"
            or int(outcome.get("horizon_bars") or 0) != 16
            or float(outcome.get("target_r") or 0.0) != 1.5
            or not isinstance(outcome.get("stop_pips"), (int, float))
            or float(outcome["stop_pips"]) <= 0
            or not isinstance(outcome.get("spread_pips"), (int, float))
            or not isinstance(outcome.get("realized_net_r"), (int, float))
        ):
            continue
        candidates.append(
            {
                "event": event,
                "outcome": outcome,
                "signal_id": _signal_id(event, outcome),
                "decision_time_utc": str(event["decision_time_utc"]),
            }
        )
    next_available: dict[str, datetime] = {}
    independent = []
    for row in sorted(candidates, key=lambda value: (value["decision_time_utc"], value["signal_id"])):
        decision = parse_utc(row["decision_time_utc"])
        if decision < next_available.get(
            row["signal_id"], datetime.min.replace(tzinfo=timezone.utc)
        ):
            continue
        independent.append(row)
        next_available[row["signal_id"]] = decision + timedelta(hours=4)
    return independent


def _evaluate_population(
    rows: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    instrument: str,
    policies: list[str],
    control_tolerance_r: float,
) -> dict[str, Any]:
    pip_size = PIP_SIZE_BY_INSTRUMENT[instrument]
    candle_starts = [parse_utc(row["start_time_utc"]) for row in candles]
    evaluated = []
    exclusions: dict[str, int] = defaultdict(int)
    for row in rows:
        event = row["event"]
        outcome = row["outcome"]
        decision = parse_utc(row["decision_time_utc"])
        indices = [index for index, value in enumerate(candle_starts) if value >= decision]
        if not indices:
            exclusions["NO_FORWARD_CANDLES"] += 1
            continue
        start_index = indices[0]
        forward = candles[start_index : start_index + 16]
        if len(forward) < 16:
            exclusions["INCOMPLETE_HORIZON"] += 1
            continue
        spread_pips = float(outcome["spread_pips"])
        stop_pips = float(outcome["stop_pips"])
        direction = str(event.get("direction") or "")
        mid_open = float(forward[0]["open"])
        entry = (
            mid_open + spread_pips * pip_size / 2.0
            if direction == "LONG"
            else mid_open - spread_pips * pip_size / 2.0
        )
        risk_distance = stop_pips * pip_size
        spread_r = spread_pips / stop_pips
        results = {
            policy: _simulate_policy(
                forward,
                direction=direction,
                entry=entry,
                risk_distance=risk_distance,
                spread_r=spread_r,
                policy=policy,
            )
            for policy in policies
        }
        stored = float(outcome["realized_net_r"])
        if abs(results["CONTROL_1_5R"]["net_r"] - stored) > control_tolerance_r:
            exclusions["CONTROL_REPLAY_MISMATCH"] += 1
            continue
        evaluated.append(
            {
                "event_id": event["event_id"],
                "signal_id": row["signal_id"],
                "mechanism_id": event.get("mechanism_id"),
                "setup_id": event.get("setup_id"),
                "decision_time_utc": row["decision_time_utc"],
                "stored_control_net_r": stored,
                "policies": results,
            }
        )

    policy_rows = []
    control_values = [row["policies"]["CONTROL_1_5R"]["net_r"] for row in evaluated]
    for policy in policies:
        values = [row["policies"][policy]["net_r"] for row in evaluated]
        differences = [value - control for value, control in zip(values, control_values)]
        ordered = sorted(zip(evaluated, values), key=lambda item: item[0]["decision_time_utc"])
        midpoint = len(ordered) // 2
        policy_rows.append(
            {
                "policy": policy,
                "summary": _summary(values),
                "average_paired_lift_r": round(statistics.fmean(differences), 6) if differences else None,
                "median_paired_lift_r": round(statistics.median(differences), 6) if differences else None,
                "better_count": sum(value > 1e-9 for value in differences),
                "worse_count": sum(value < -1e-9 for value in differences),
                "tie_count": sum(abs(value) <= 1e-9 for value in differences),
                "first_half_average_net_r": (
                    round(statistics.fmean(value for _, value in ordered[:midpoint]), 6)
                    if midpoint
                    else None
                ),
                "second_half_average_net_r": (
                    round(statistics.fmean(value for _, value in ordered[midpoint:]), 6)
                    if ordered[midpoint:]
                    else None
                ),
                "p_value": round(_paired_sign_p_value(differences), 8),
                "fdr_q_value": None,
            }
        )
    return {
        "eligible_independent_count": len(rows),
        "replay_validated_count": len(evaluated),
        "exclusion_counts": dict(sorted(exclusions.items())),
        "control_replay_tolerance_r": control_tolerance_r,
        "policy_results": policy_rows,
        "events": evaluated,
    }


def build_exit_management_report(
    connection,
    evidence_inbox: Path,
    market_inbox: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    instrument = str(contract["instrument"])
    evidence = _load_evidence(connection, evidence_inbox, instrument)
    strategy_events = list(evidence["strategy_events"].values())
    strategy_outcomes = list(evidence["strategy_outcomes"].values())
    candidate_events, candidate_outcomes = _candidate_strategy_facts(
        list(evidence["candidates"].values()),
        list(evidence["outcomes"].values()),
    )
    populations = {
        "ORIGINAL_FAILED_AUCTION_CANDIDATES": _population_rows(
            candidate_events, candidate_outcomes, instrument
        ),
        "STRATEGY_SHADOW": _population_rows(
            strategy_events, strategy_outcomes, instrument
        ),
    }
    all_rows = [row for rows in populations.values() for row in rows]
    if not all_rows:
        raise ValueError("no eligible outcomes for exit-management replay")
    start = min(parse_utc(row["decision_time_utc"]) for row in all_rows)
    end = max(parse_utc(row["decision_time_utc"]) for row in all_rows) + timedelta(hours=4)
    candles, manifest_ids = _load_m15_candles(
        connection, market_inbox, instrument, start, end
    )
    policies = [str(value["policy_id"]) for value in contract["policies"]]
    reports = {
        name: _evaluate_population(
            rows,
            candles,
            instrument,
            policies,
            float(contract["control_replay_tolerance_r"]),
        )
        for name, rows in populations.items()
    }
    comparisons = [
        row
        for report in reports.values()
        for row in report["policy_results"]
        if row["policy"] != "CONTROL_1_5R"
    ]
    _apply_benjamini_hochberg(comparisons)
    return {
        "schema": "FX_EXIT_MANAGEMENT_RESEARCH_V1",
        "generated_at_utc": utc_now(),
        "contract": contract,
        "contract_sha256": __import__("hashlib").sha256(
            canonical_json(contract).encode("utf-8")
        ).hexdigest(),
        "market_manifest_count": len(manifest_ids),
        "market_manifest_ids": manifest_ids,
        "populations": reports,
        "fdr_family_size": len(comparisons),
        "fdr_significant_comparison_count": sum(
            float(row["fdr_q_value"]) <= 0.05 for row in comparisons
        ),
        "interpretation": {
            "historical_post_hoc_research": True,
            "paired_same_event_comparison": True,
            "m15_intrabar_order_unknown": True,
            "same_bar_policy": "STOP_FIRST_CONSERVATIVE",
            "management_activation": "NEXT_CANDLE_AFTER_1R_TOUCH",
            "no_automatic_campaign_creation": True,
            "no_policy_or_execution_authority": True,
        },
    }
