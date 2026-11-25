from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .experiments import _load_evidence


PIP_SIZE_BY_INSTRUMENT = {"EUR_USD": 0.0001, "GBP_USD": 0.0001, "AUD_USD": 0.0001, "USD_JPY": 0.01}
MISSING_CONTEXT_PREFIXES = ("NOT_", "UNAVAILABLE", "UNKNOWN", "NONE")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_r"]) for row in rows]
    winners = sum(value > 0 for value in values)
    return {
        "count": len(values),
        "positive_count": winners,
        "positive_rate": round(winners / len(values), 6) if values else None,
        "average_net_r": round(statistics.fmean(values), 6) if values else None,
        "median_net_r": round(statistics.median(values), 6) if values else None,
        "small_sample": len(values) < 30,
    }


def _fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    row_one = a + b
    row_two = c + d
    column_one = a + c
    total = row_one + row_two
    denominator = math.comb(total, column_one)
    observed = math.comb(row_one, a) * math.comb(row_two, c) / denominator
    lower = max(0, column_one - row_two)
    upper = min(row_one, column_one)
    probability = 0.0
    for value in range(lower, upper + 1):
        candidate = (
            math.comb(row_one, value)
            * math.comb(row_two, column_one - value)
            / denominator
        )
        if candidate <= observed + 1e-12:
            probability += candidate
    return min(1.0, probability)


def _apply_benjamini_hochberg(rows: list[dict[str, Any]]) -> None:
    ordered = sorted(enumerate(rows), key=lambda item: item[1]["p_value"])
    total = len(ordered)
    next_q = 1.0
    for reverse_rank, (index, row) in enumerate(reversed(ordered), start=1):
        rank = total - reverse_rank + 1
        next_q = min(next_q, float(row["p_value"]) * total / rank)
        rows[index]["fdr_q_value"] = round(min(1.0, next_q), 6)


def _available_category(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or normalized.upper().startswith(MISSING_CONTEXT_PREFIXES):
        return None
    return normalized


def _bucket(value: float, cuts: tuple[float, float, float], labels: tuple[str, str, str, str]) -> str:
    if value <= cuts[0]:
        return labels[0]
    if value <= cuts[1]:
        return labels[1]
    if value <= cuts[2]:
        return labels[2]
    return labels[3]


def _direction_alignment(state_direction: str, signal_direction: str) -> str | None:
    state = state_direction.upper()
    signal = signal_direction.upper()
    if state == "FLAT" or signal not in {"LONG", "SHORT"}:
        return "FLAT" if state == "FLAT" else None
    if state not in {"UP", "DOWN"}:
        return None
    return (
        "ALIGNED"
        if (state == "UP" and signal == "LONG")
        or (state == "DOWN" and signal == "SHORT")
        else "OPPOSED"
    )


def _contexts(event: dict[str, Any]) -> dict[str, str]:
    packet = event.get("feature_packet") if isinstance(event.get("feature_packet"), dict) else {}
    contexts: dict[str, str] = {}
    for dimension, source in (
        ("session_bucket", packet.get("session_bucket")),
        ("direction", event.get("direction")),
        ("markov_state", packet.get("markov_state")),
        ("hmm_state", packet.get("hmm_state")),
        ("garch_state", packet.get("garch_volatility_state")),
    ):
        if (category := _available_category(source)) is not None:
            contexts[dimension] = category
    signal_direction = str(event.get("direction") or "")
    hmm_state = _available_category(packet.get("hmm_state"))
    if hmm_state and hmm_state.startswith("HMM_"):
        hmm_direction = hmm_state.split("_", 2)[1]
        if (alignment := _direction_alignment(hmm_direction, signal_direction)):
            contexts["hmm_direction_alignment"] = alignment
    markov_state = _available_category(packet.get("markov_state"))
    if markov_state and "|" in markov_state:
        parts = markov_state.split("|")
        if len(parts) >= 2 and (
            alignment := _direction_alignment(parts[1], signal_direction)
        ):
            contexts["markov_direction_alignment"] = alignment
    h1 = str(packet.get("h1_trend_state") or "")
    h4 = str(packet.get("h4_trend_state") or "")
    if h1 and h4:
        contexts["htf_alignment"] = f"{h1}_{h4}"
    elif (alignment := _available_category(packet.get("htf_alignment"))) is not None:
        contexts["htf_alignment"] = alignment
    if isinstance(packet.get("maximum_touch_index"), int):
        contexts["maximum_touch_index"] = str(packet["maximum_touch_index"])
    atr = packet.get("atr_pips")
    spread = packet.get("spread_pips")
    if isinstance(atr, (int, float)) and float(atr) > 0 and isinstance(spread, (int, float)):
        contexts["spread_to_atr"] = _bucket(
            float(spread) / float(atr),
            (0.35, 0.5, 0.75),
            ("LE_0_35", "GT_0_35_LE_0_50", "GT_0_50_LE_0_75", "GT_0_75"),
        )
    candle = packet.get("candle") if isinstance(packet.get("candle"), dict) else {}
    instrument = str(event.get("instrument") or "")
    pip_size = PIP_SIZE_BY_INSTRUMENT.get(instrument)
    if pip_size and all(isinstance(candle.get(key), (int, float)) for key in ("open", "high", "low", "close")):
        sign = 1.0 if str(event.get("direction")) == "LONG" else -1.0
        signed_body = (float(candle["close"]) - float(candle["open"])) / pip_size * sign
        candle_range = (float(candle["high"]) - float(candle["low"])) / pip_size
        contexts["signal_body_pips"] = _bucket(
            signed_body,
            (1.0, 3.0, 6.0),
            ("LE_1", "GT_1_LE_3", "GT_3_LE_6", "GT_6"),
        )
        if isinstance(atr, (int, float)) and float(atr) > 0:
            contexts["candle_range_to_atr"] = _bucket(
                candle_range / float(atr),
                (0.75, 1.0, 1.5),
                ("LE_0_75", "GT_0_75_LE_1", "GT_1_LE_1_5", "GT_1_5"),
            )
    return contexts


def _signal_id(event: dict[str, Any], outcome: dict[str, Any]) -> str:
    return "|".join(
        str(value)
        for value in (
            event.get("instrument"),
            event.get("mechanism_id"),
            event.get("setup_id"),
            outcome.get("entry_model"),
            outcome.get("horizon_bars"),
            outcome.get("target_r"),
            outcome.get("same_bar_tie_policy"),
            outcome.get("outcome_source") or "STRATEGY_SHADOW",
        )
    )


def _enrichment_index(
    enrichment: dict[str, Any] | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    if not enrichment:
        return {}
    if enrichment.get("schema") != "FX_SIGNAL_REGIME_ENRICHMENT_V1":
        raise ValueError("unsupported signal regime enrichment schema")
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in enrichment.get("rows") or []:
        key = (str(row.get("source_population")), str(row.get("source_id")))
        if not all(key):
            raise ValueError("regime enrichment row is missing its source identity")
        existing = index.get(key)
        if existing is not None and existing != row:
            raise ValueError(f"conflicting regime enrichment row: {key}")
        index[key] = row
    return index


def _apply_regime_enrichment(
    packet: dict[str, Any],
    event: dict[str, Any],
    enrichment: dict[str, Any] | None,
) -> dict[str, Any]:
    if not enrichment or enrichment.get("status") not in {"READY", "PARTIAL"}:
        return packet
    if enrichment.get("decision_time_utc") != event.get("decision_time_utc"):
        raise ValueError("regime enrichment decision time does not match source event")
    enriched = dict(packet)
    markov = enrichment.get("markov") or {}
    hmm = enrichment.get("hmm") or {}
    garch = enrichment.get("garch") or {}
    if markov.get("state_id"):
        enriched["markov_state"] = markov["state_id"]
    if hmm.get("state_id"):
        enriched["hmm_state"] = hmm["state_id"]
    if garch.get("volatility_state"):
        enriched["garch_volatility_state"] = garch["volatility_state"]
    enriched["historical_regime_enrichment"] = {
        "historical_causal_not_forward": True,
        "model_contract_sha256": enrichment.get("model_contract_sha256"),
        "source_manifest_set_sha256": enrichment.get(
            "source_manifest_set_sha256"
        ),
    }
    return enriched


def _candidate_strategy_facts(
    candidates: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    enrichment: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates_by_id = {str(row.get("candidate_id")): row for row in candidates}
    events: list[dict[str, Any]] = []
    translated_outcomes: list[dict[str, Any]] = []
    for outcome in outcomes:
        if outcome.get("arm_id") != "RULE_BASELINE":
            continue
        candidate = candidates_by_id.get(str(outcome.get("candidate_id")))
        if candidate is None:
            continue
        event_id = f"CANDIDATE::{outcome.get('outcome_id')}"
        market = candidate.get("market_facts") if isinstance(candidate.get("market_facts"), dict) else {}
        packet = dict(market)
        packet["maximum_touch_index"] = max(
            (
                int(level.get("touch_index") or 0)
                for level in candidate.get("objective_levels", [])
                if isinstance(level, dict)
            ),
            default=0,
        )
        packet = _apply_regime_enrichment(
            packet,
            candidate,
            (enrichment or {}).get(
                ("ORIGINAL_FAILED_AUCTION_CANDIDATE", str(candidate["candidate_id"]))
            ),
        )
        events.append(
            {
                "event_id": event_id,
                "instrument": candidate.get("instrument"),
                "mechanism_id": candidate.get("mechanism_class"),
                "setup_id": candidate.get("level_signature") or "UNSPECIFIED_LEVEL",
                "direction": candidate.get("direction"),
                "decision_time_utc": candidate.get("decision_time_utc"),
                "feature_packet": packet,
            }
        )
        translated_outcomes.append({**outcome, "event_id": event_id})
    return events, translated_outcomes


def _independent_rows(
    events: list[dict[str, Any]], outcomes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    outcomes_by_event = {str(row.get("event_id")): row for row in outcomes}
    rows = []
    for event in events:
        outcome = outcomes_by_event.get(str(event.get("event_id")))
        if not outcome or not isinstance(outcome.get("realized_net_r"), (int, float)):
            continue
        decision_time = str(event.get("decision_time_utc") or "")
        if not decision_time:
            continue
        rows.append(
            {
                "signal_id": _signal_id(event, outcome),
                "mechanism_id": str(event.get("mechanism_id") or ""),
                "setup_id": str(event.get("setup_id") or ""),
                "decision_time_utc": decision_time,
                "horizon_bars": int(outcome.get("horizon_bars") or 0),
                "net_r": float(outcome["realized_net_r"]),
                "contexts": _contexts(event),
            }
        )
    next_available: dict[str, datetime] = {}
    independent = []
    for row in sorted(rows, key=lambda value: (value["decision_time_utc"], value["signal_id"])):
        decision = datetime.fromisoformat(row["decision_time_utc"].replace("Z", "+00:00")).astimezone(timezone.utc)
        if decision < next_available.get(row["signal_id"], datetime.min.replace(tzinfo=timezone.utc)):
            continue
        independent.append(row)
        next_available[row["signal_id"]] = decision + timedelta(minutes=15 * row["horizon_bars"])
    return independent


def build_strategy_context_report(
    events: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    *,
    minimum_slice_count: int = 5,
) -> dict[str, Any]:
    rows = _independent_rows(events, outcomes)
    by_signal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_signal[row["signal_id"]].append(row)
    signal_summaries = [
        {
            "signal_id": signal_id,
            "mechanism_id": signal_rows[0]["mechanism_id"],
            "setup_id": signal_rows[0]["setup_id"],
            **_summary(signal_rows),
        }
        for signal_id, signal_rows in sorted(by_signal.items())
    ]
    slices: list[dict[str, Any]] = []
    coverage: dict[str, int] = defaultdict(int)
    for row in rows:
        for dimension in row["contexts"]:
            coverage[dimension] += 1
    for signal_id, signal_rows in sorted(by_signal.items()):
        baseline = _summary(signal_rows)
        dimensions = sorted({key for row in signal_rows for key in row["contexts"]})
        for dimension in dimensions:
            values = sorted({row["contexts"].get(dimension) for row in signal_rows if row["contexts"].get(dimension)})
            for value in values:
                treatment = [row for row in signal_rows if row["contexts"].get(dimension) == value]
                comparator = [row for row in signal_rows if row["contexts"].get(dimension) != value]
                if len(treatment) < minimum_slice_count or len(comparator) < minimum_slice_count:
                    continue
                treatment_summary = _summary(treatment)
                comparator_summary = _summary(comparator)
                p_value = _fisher_two_sided(
                    treatment_summary["positive_count"],
                    treatment_summary["count"] - treatment_summary["positive_count"],
                    comparator_summary["positive_count"],
                    comparator_summary["count"] - comparator_summary["positive_count"],
                )
                slices.append(
                    {
                        "signal_id": signal_id,
                        "mechanism_id": signal_rows[0]["mechanism_id"],
                        "setup_id": signal_rows[0]["setup_id"],
                        "dimension": dimension,
                        "value": value,
                        "treatment": treatment_summary,
                        "comparator": comparator_summary,
                        "average_net_r_lift": round(
                            float(treatment_summary["average_net_r"])
                            - float(comparator_summary["average_net_r"]),
                            6,
                        ),
                        "positive_rate_lift": round(
                            float(treatment_summary["positive_rate"])
                            - float(comparator_summary["positive_rate"]),
                            6,
                        ),
                        "p_value": round(p_value, 6),
                        "fdr_q_value": None,
                        "descriptive_only": True,
                        "baseline": baseline,
                    }
                )
    _apply_benjamini_hochberg(slices)
    slices.sort(
        key=lambda row: (
            row["fdr_q_value"],
            -abs(row["average_net_r_lift"]),
            row["signal_id"],
            row["dimension"],
            row["value"],
        )
    )
    pooled: list[dict[str, Any]] = []
    context_keys = sorted({(dimension, value) for row in rows for dimension, value in row["contexts"].items()})
    baselines = {signal_id: statistics.fmean(row["net_r"] for row in signal_rows) for signal_id, signal_rows in by_signal.items()}
    for dimension, value in context_keys:
        selected = [row for row in rows if row["contexts"].get(dimension) == value]
        signal_count = len({row["signal_id"] for row in selected})
        if len(selected) < 10 or signal_count < 2:
            continue
        residuals = [row["net_r"] - baselines[row["signal_id"]] for row in selected]
        pooled.append(
            {
                "dimension": dimension,
                "value": value,
                "count": len(selected),
                "distinct_signal_count": signal_count,
                "average_within_signal_residual_r": round(statistics.fmean(residuals), 6),
                "descriptive_only": True,
            }
        )
    pooled.sort(key=lambda row: -abs(row["average_within_signal_residual_r"]))
    return {
        "independent_outcome_count": len(rows),
        "signal_count": len(by_signal),
        "signal_summaries": signal_summaries,
        "context_coverage_counts": dict(sorted(coverage.items())),
        "tested_slice_count": len(slices),
        "fdr_significant_slice_count": sum(row["fdr_q_value"] <= 0.05 for row in slices),
        "context_slices": slices,
        "pooled_within_signal_context": pooled,
        "independence_policy": "FIRST_EVENT_PER_SIGNAL_NON_OVERLAPPING_FIXED_HORIZON",
    }


def build_signal_context_forensics(
    connection,
    evidence_inbox_dir: Path,
    *,
    instrument: str = "EUR_USD",
    minimum_slice_count: int = 5,
    regime_enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = _load_evidence(connection, evidence_inbox_dir, instrument)
    enrichment = _enrichment_index(regime_enrichment)
    strategy_events = []
    for event in evidence["strategy_events"].values():
        packet = (
            event.get("feature_packet")
            if isinstance(event.get("feature_packet"), dict)
            else {}
        )
        strategy_events.append(
            {
                **event,
                "feature_packet": _apply_regime_enrichment(
                    packet,
                    event,
                    enrichment.get(
                        ("STRATEGY_SHADOW_EVENT", str(event.get("event_id")))
                    ),
                ),
            }
        )
    strategy = build_strategy_context_report(
        strategy_events,
        list(evidence["strategy_outcomes"].values()),
        minimum_slice_count=minimum_slice_count,
    )
    candidate_events, candidate_outcomes = _candidate_strategy_facts(
        list(evidence["candidates"].values()),
        list(evidence["outcomes"].values()),
        enrichment,
    )
    original_candidates = build_strategy_context_report(
        candidate_events,
        candidate_outcomes,
        minimum_slice_count=minimum_slice_count,
    )
    return {
        "schema": "FX_SIGNAL_CONTEXT_FORENSICS_V1",
        "generated_at_utc": utc_now(),
        "instrument": instrument,
        "evidence_manifest_count": len(evidence["manifest_ids"]),
        "regime_enrichment": {
            "artifact_id": (regime_enrichment or {}).get("artifact_id"),
            "row_count": len(enrichment),
            "historical_causal_not_forward": bool(enrichment),
        },
        "original_failed_auction_candidates": original_candidates,
        "strategy_shadow": strategy,
        "interpretation": {
            "fdr_scope": "ALL_ELIGIBLE_WITHIN_SIGNAL_CATEGORICAL_CONTEXT_SLICES",
            "post_hoc_results_are_not_confirmation": True,
            "missing_regime_labels_are_not_backfilled": True,
            "outcome_types_pooled": False,
        },
        "authority": {
            "research_only": True,
            "automatic_campaign_creation": False,
            "automatic_policy_changes": False,
            "automatic_execution_changes": False,
            "order_authority": False,
        },
    }
