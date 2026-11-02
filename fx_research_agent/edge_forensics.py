from __future__ import annotations

import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .result_packages import LEGACY_MECHANISM_CLASSES


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _summary(values: Iterable[float]) -> dict[str, Any]:
    rows = [float(value) for value in values]
    return {
        "count": len(rows),
        "average": round(statistics.fmean(rows), 6) if rows else None,
        "median": round(float(statistics.median(rows)), 6) if rows else None,
        "positive_rate": (
            round(sum(value > 0 for value in rows) / len(rows), 6) if rows else None
        ),
    }


def _signal_metric(stage: dict[str, Any], name: str) -> float | None:
    signal = stage.get("signal") if isinstance(stage.get("signal"), dict) else {}
    return _number(signal.get(name))


def _failed_gate_categories(failed_gates: Iterable[Any]) -> list[str]:
    categories: set[str] = set()
    for raw in failed_gates:
        gate = str(raw).lower()
        if "sample" in gate or "event" in gate or "count" in gate:
            categories.add("SAMPLE_ADEQUACY")
        if "control" in gate or "edge_over" in gate:
            categories.add("CONTROL_SPECIFICITY")
        if "cost" in gate:
            categories.add("COST_STRESS")
        if "oos" in gate or "out_of_sample" in gate or "chronological" in gate:
            categories.add("OOS_DECAY")
        if "month" in gate or "year" in gate or "trimmed" in gate:
            categories.add("TEMPORAL_STABILITY")
        if "avg_net" in gate or "average_net" in gate:
            categories.add("BASELINE_EXPECTANCY")
    return sorted(categories)


def analyze_pair_research(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT instrument, hypothesis_id, result_status, payload_json "
        "FROM external_research_results WHERE instrument != 'EUR_USD' "
        "ORDER BY instrument, hypothesis_id"
    ).fetchall()
    results: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    for row in rows:
        payload = json.loads(row["payload_json"])
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        development = (
            metrics.get("development")
            if isinstance(metrics.get("development"), dict)
            else {}
        )
        signal = (
            development.get("signal")
            if isinstance(development.get("signal"), dict)
            else {}
        )
        metric_unit = "R" if signal.get("avg_net_r") is not None else "PIPS"
        metric_name = "avg_net_r" if metric_unit == "R" else "avg_net_pips"
        baseline = _number(signal.get(metric_name))
        oos = development.get("oos") if isinstance(development.get("oos"), dict) else {}
        oos_average = _number(oos.get(metric_name))
        edge = _number(
            development.get("edge_over_best_control_r")
            if metric_unit == "R"
            else development.get("edge_over_best_shifted_pivot_pips")
        )
        if edge is None:
            edge = _number(development.get("edge_over_causal_control_r"))
        stress = (
            development.get("cost_stress")
            if isinstance(development.get("cost_stress"), dict)
            else {}
        )
        stress_values = [
            value
            for value in (
                _number(item.get(metric_name))
                for item in stress.values()
                if isinstance(item, dict)
            )
            if value is not None
        ]
        worst_cost = min(stress_values) if stress_values else None
        failed_gates = [str(value) for value in development.get("failed_gates", [])]
        categories = _failed_gate_categories(failed_gates)
        category_counts.update(categories)
        results.append(
            {
                "instrument": str(row["instrument"]),
                "hypothesis_id": str(row["hypothesis_id"]),
                "result_status": str(row["result_status"]),
                "mechanism_class": payload.get("mechanism_class")
                or LEGACY_MECHANISM_CLASSES.get(str(row["hypothesis_id"])),
                "metric_unit": metric_unit,
                "development_sample_count": signal.get("count"),
                "development_average": baseline,
                "development_positive_rate": _number(signal.get("positive_rate")),
                "chronological_oos_average": oos_average,
                "edge_over_best_control": edge,
                "worst_cost_stress_average": worst_cost,
                "additional_cost_erosion": (
                    round(baseline - worst_cost, 6)
                    if baseline is not None and worst_cost is not None
                    else None
                ),
                "failed_gate_categories": categories,
                "failed_gates": failed_gates,
            }
        )
    r_results = [row for row in results if row["metric_unit"] == "R"]
    r_cost_erosion = [
        float(row["additional_cost_erosion"])
        for row in r_results
        if row["additional_cost_erosion"] is not None
    ]
    return {
        "study_count": len(results),
        "r_metric_study_count": len(r_results),
        "development_positive_count": sum(
            row["development_average"] is not None and row["development_average"] > 0
            for row in results
        ),
        "r_development_positive_count": sum(
            row["development_average"] is not None and row["development_average"] > 0
            for row in r_results
        ),
        "development_and_oos_positive_count": sum(
            row["development_average"] is not None
            and row["development_average"] > 0
            and row["chronological_oos_average"] is not None
            and row["chronological_oos_average"] > 0
            for row in results
        ),
        "positive_baseline_erased_by_cost_count": sum(
            row["development_average"] is not None
            and row["development_average"] > 0
            and row["worst_cost_stress_average"] is not None
            and row["worst_cost_stress_average"] <= 0
            for row in results
        ),
        "average_additional_cost_erosion_r": (
            round(statistics.fmean(r_cost_erosion), 6) if r_cost_erosion else None
        ),
        "failed_gate_category_counts": dict(sorted(category_counts.items())),
        "results": results,
    }


def analyze_eur_profiles(validation_path: Path, dated_path: Path) -> dict[str, Any]:
    validation = _read_json(validation_path)
    dated = _read_json(dated_path)
    dated_by_id = {
        str(row.get("profile_id")): row for row in dated.get("profile_rows", [])
    }
    rows: list[dict[str, Any]] = []
    for profile in validation.get("profile_rows", []):
        evidence = (
            profile.get("research_evidence")
            if isinstance(profile.get("research_evidence"), dict)
            else {}
        )
        forward = dated_by_id.get(str(profile.get("profile_id")), {})
        metrics = forward.get("metrics") if isinstance(forward.get("metrics"), dict) else {}
        rows.append(
            {
                "profile_id": profile.get("profile_id"),
                "family_id": profile.get("family_id"),
                "direction": profile.get("direction"),
                "profile_status": profile.get("profile_status"),
                "historical_event_count": evidence.get("unique_market_event_count"),
                "historical_average_net_r": _number(evidence.get("signal_avg_net_r_close")),
                "historical_edge_over_control_r": _number(
                    evidence.get("edge_vs_best_control_net_r")
                ),
                "historical_positive_month_rate": _number(
                    evidence.get("positive_month_rate")
                ),
                "historical_worst_month_net_r": _number(
                    evidence.get("worst_month_avg_net_r")
                ),
                "forward_exact_match_count": forward.get("exact_match_count", 0),
                "forward_ready_outcome_count": forward.get("ready_outcome_count", 0),
                "forward_average_net_r": _number(metrics.get("avg_net_r")),
                "forward_state": forward.get("dated_confirmation_state"),
            }
        )
    return {
        "profile_count": len(rows),
        "historically_positive_count": sum(
            row["historical_average_net_r"] is not None
            and row["historical_average_net_r"] > 0
            for row in rows
        ),
        "forward_exact_match_count": sum(
            int(row["forward_exact_match_count"] or 0) for row in rows
        ),
        "forward_ready_outcome_count": sum(
            int(row["forward_ready_outcome_count"] or 0) for row in rows
        ),
        "profiles": rows,
    }


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _outcome_summary(rows: list[sqlite3.Row]) -> dict[str, Any]:
    net = [float(row["realized_net_r"]) for row in rows]
    mfe = [float(row["mfe_r"]) for row in rows if row["mfe_r"] is not None]
    mae = [float(row["mae_r"]) for row in rows if row["mae_r"] is not None]
    spread_r: list[float] = []
    for row in rows:
        payload = json.loads(row["outcome_json"])
        spread = _number(payload.get("spread_pips"))
        stop = _number(payload.get("stop_pips"))
        if spread is not None and stop is not None and stop > 0:
            spread_r.append(spread / stop)
    net_summary = _summary(net)
    average_spread_r = statistics.fmean(spread_r) if spread_r else None
    return {
        "net_r": net_summary,
        "average_mfe_r": round(statistics.fmean(mfe), 6) if mfe else None,
        "average_mae_r": round(statistics.fmean(mae), 6) if mae else None,
        "mfe_at_least_1r_rate": round(sum(value >= 1.0 for value in mfe) / len(mfe), 6)
        if mfe
        else None,
        "mfe_at_least_1_5r_rate": round(
            sum(value >= 1.5 for value in mfe) / len(mfe), 6
        )
        if mfe
        else None,
        "mae_at_least_1r_rate": round(sum(value >= 1.0 for value in mae) / len(mae), 6)
        if mae
        else None,
        "average_entry_spread_r_proxy": round(average_spread_r, 6)
        if average_spread_r is not None
        else None,
        "average_net_plus_entry_spread_r_proxy": round(
            float(net_summary["average"]) + average_spread_r, 6
        )
        if net_summary["average"] is not None and average_spread_r is not None
        else None,
        "cost_proxy_caveat": (
            "Adds decision spread divided by modeled stop distance. It is diagnostic, "
            "not a reconstructed zero-cost backtest."
        ),
    }


def analyze_agent_forward(agent_db_path: Path, experiment_contract_path: Path) -> dict[str, Any]:
    contract = _read_json(experiment_contract_path)
    cutover = str(contract["experiment_epoch_started_at_utc"])
    connection = _connect_read_only(agent_db_path)
    try:
        baseline_rows = connection.execute(
            """
            SELECT c.candidate_id, c.mechanism_class, c.decision_time_utc,
                   o.realized_net_r, o.mfe_r, o.mae_r,
                   o.payload_json AS outcome_json, l.episode_id
              FROM agent_decisions d
              JOIN candidates c ON c.candidate_id=d.candidate_id
              JOIN decision_outcomes o ON o.decision_id=d.decision_id
              LEFT JOIN candidate_episode_links l ON l.candidate_id=c.candidate_id
             WHERE d.arm_id='RULE_BASELINE' AND d.decided_at_utc >= ?
             ORDER BY c.decision_time_utc, c.candidate_id
            """,
            (cutover,),
        ).fetchall()
        first_by_episode: dict[str, sqlite3.Row] = {}
        for row in baseline_rows:
            key = str(row["episode_id"] or f"CANDIDATE::{row['candidate_id']}")
            first_by_episode.setdefault(key, row)
        independent_rows = list(first_by_episode.values())

        review_rows = connection.execute(
            """
            SELECT c.candidate_id, c.mechanism_class, c.decision_time_utc,
                   o.realized_net_r, o.mfe_r, o.mae_r,
                   o.payload_json AS outcome_json, l.episode_id
              FROM agent_decisions d
              JOIN candidates c ON c.candidate_id=d.candidate_id
              JOIN decision_outcomes o ON o.decision_id=d.decision_id
              LEFT JOIN strategy_review_episode_links l ON l.candidate_id=c.candidate_id
             WHERE d.arm_id='LLM_STRATEGY_REVIEW_V2_SHADOW'
             ORDER BY c.decision_time_utc, c.candidate_id
            """
        ).fetchall()
        broker = connection.execute(
            """
            SELECT COUNT(*) AS order_count,
                   COALESCE(SUM(realized_pnl_usd), 0.0) AS realized_pnl_usd
              FROM broker_orders b
              JOIN agent_decisions d ON d.decision_id=b.decision_id
             WHERE d.decided_at_utc >= ?
            """,
            (cutover,),
        ).fetchone()
    finally:
        connection.close()

    mechanism_rows: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in review_rows:
        mechanism_rows[str(row["mechanism_class"])].append(row)
    review_by_mechanism = []
    for mechanism, source_rows in sorted(mechanism_rows.items()):
        linked_first: dict[str, sqlite3.Row] = {}
        for row in source_rows:
            if row["episode_id"]:
                linked_first.setdefault(str(row["episode_id"]), row)
        review_by_mechanism.append(
            {
                "mechanism_class": mechanism,
                "candidate_level": _outcome_summary(source_rows),
                "strict_linked_episode_level": _outcome_summary(
                    list(linked_first.values())
                ),
                "strict_linked_episode_count": len(linked_first),
                "small_sample": len(linked_first) < 30,
            }
        )
    baseline_summary = _outcome_summary(independent_rows)
    return {
        "experiment_epoch": contract.get("experiment_epoch"),
        "experiment_cutover_utc": cutover,
        "rule_baseline_candidate_outcome_count": len(baseline_rows),
        "rule_baseline_independent_episode_count": len(independent_rows),
        "rule_baseline_independent_episode_summary": baseline_summary,
        "strategy_review_v2": {
            "candidate_outcome_count": len(review_rows),
            "mechanism_rows": review_by_mechanism,
            "interpretation": (
                "Candidate-level rows are descriptive. Only linked episode-level rows "
                "have strict within-mechanism episode deduplication, and all are small samples."
            ),
        },
        "practice_trade_count": int(broker["order_count"] or 0),
        "realized_practice_pnl_usd": round(float(broker["realized_pnl_usd"] or 0.0), 6),
        "realized_practice_pnl_available": int(broker["order_count"] or 0) > 0,
    }


def _conclusions(
    pair_research: dict[str, Any],
    eur_profiles: dict[str, Any],
    agent_forward: dict[str, Any],
) -> list[dict[str, str]]:
    conclusions: list[dict[str, str]] = []
    if pair_research["r_development_positive_count"] <= 1:
        conclusions.append(
            {
                "code": "CROSS_PAIR_DISCOVERY_WEAK",
                "finding": (
                    f"Only {pair_research['r_development_positive_count']} of "
                    f"{pair_research['r_metric_study_count']} R-based non-EUR studies "
                    "had positive development expectancy."
                ),
            }
        )
    baseline = agent_forward["rule_baseline_independent_episode_summary"]
    net_average = baseline["net_r"]["average"]
    gross_proxy = baseline["average_net_plus_entry_spread_r_proxy"]
    if net_average is not None and net_average < 0 and gross_proxy is not None and gross_proxy > 0:
        conclusions.append(
            {
                "code": "AGENT_COST_GEOMETRY_MATERIAL",
                "finding": (
                    "The independent EUR-agent baseline is negative net, while the entry-spread "
                    "add-back proxy is positive. Costs and stop geometry are material, but the "
                    "proxy is not proof of zero-cost edge."
                ),
            }
        )
    if (
        baseline["average_mfe_r"] is not None
        and baseline["average_mae_r"] is not None
        and baseline["average_mfe_r"] >= 0.8
        and baseline["average_mae_r"] >= 0.8
    ):
        conclusions.append(
            {
                "code": "AGENT_DIRECTION_TIMING_AMBIGUOUS",
                "finding": (
                    "Average favorable and adverse excursions are both near or above 1R, "
                    "consistent with whipsaw and weak directional selection rather than a "
                    "simple absence of movement."
                ),
            }
        )
    if eur_profiles["forward_ready_outcome_count"] == 0:
        conclusions.append(
            {
                "code": "EUR_HISTORICAL_PROFILES_FORWARD_UNOBSERVED",
                "finding": (
                    "The three positive historical EUR/USD profiles still have zero exact "
                    "forward outcomes; they are unconfirmed, not forward-disproved."
                ),
            }
        )
    provisional = [
        row
        for row in agent_forward["strategy_review_v2"]["mechanism_rows"]
        if row["strict_linked_episode_level"]["net_r"]["average"] is not None
        and row["strict_linked_episode_level"]["net_r"]["average"] > 0
    ]
    if provisional:
        labels = ", ".join(
            f"{row['mechanism_class']} (n={row['strict_linked_episode_count']})"
            for row in provisional
        )
        conclusions.append(
            {
                "code": "PROVISIONAL_AGENT_MECHANISMS_TOO_SMALL",
                "finding": (
                    f"Positive strict episode averages appear for {labels}, but every "
                    "sample is below 30 and remains descriptive only."
                ),
            }
        )
    return conclusions


def build_cross_system_edge_forensics(
    research_connection: sqlite3.Connection,
    *,
    agent_db_path: Path,
    agent_experiment_contract_path: Path,
    eur_profile_validation_path: Path,
    eur_profile_dated_path: Path,
) -> dict[str, Any]:
    pair_research = analyze_pair_research(research_connection)
    eur_profiles = analyze_eur_profiles(
        eur_profile_validation_path, eur_profile_dated_path
    )
    agent_forward = analyze_agent_forward(
        agent_db_path, agent_experiment_contract_path
    )
    return {
        "schema": "FX_CROSS_SYSTEM_EDGE_FORENSICS_V1",
        "generated_at_utc": _utc_now(),
        "analysis_status": "DESCRIPTIVE_DIAGNOSTIC_COMPLETE",
        "pair_research": pair_research,
        "eur_usd_historical_profiles": eur_profiles,
        "eur_agent_forward": agent_forward,
        "conclusions": _conclusions(pair_research, eur_profiles, agent_forward),
        "authority": {
            "research_only": True,
            "automatic_strategy_changes": False,
            "lifecycle_changes": False,
            "execution_changes": False,
        },
    }
