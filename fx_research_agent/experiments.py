from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .campaigns import campaign_data_readiness, campaign_state
from .evidence import load_validated_package
from .storage import canonical_json, insert_immutable, payload_hash


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _merge_immutable(target: dict[str, dict[str, Any]], records: list[Any], key: str, kind: str) -> None:
    for value in records:
        if not isinstance(value, dict) or not value.get(key):
            raise ValueError(f"{kind} record is missing immutable key {key}")
        record_id = str(value[key])
        existing = target.get(record_id)
        if existing is not None and canonical_json(existing) != canonical_json(value):
            raise ValueError(f"conflicting immutable {kind} rewrite: {record_id}")
        target[record_id] = value


def _load_evidence(connection, inbox_dir: Path, instrument: str) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}
    contexts: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    manifest_ids: list[str] = []
    snapshot_end_utc: str | None = None
    for row in connection.execute(
        "SELECT payload_json FROM evidence_manifests WHERE usable_for_testing=1 ORDER BY registered_at_utc, manifest_id"
    ).fetchall():
        registered = json.loads(row["payload_json"])
        if registered.get("instrument") != instrument:
            continue
        manifest_path = inbox_dir / f"{registered['manifest_id']}.manifest.json"
        if not manifest_path.is_file():
            matches = list(inbox_dir.glob(f"*{registered['manifest_id']}*.manifest.json"))
            if len(matches) != 1:
                raise ValueError(f"immutable evidence manifest unavailable in inbox: {registered['manifest_id']}")
            manifest_path = matches[0]
        manifest, payload = load_validated_package(manifest_path)
        if manifest != registered:
            raise ValueError(f"registered evidence manifest differs from inbox copy: {manifest['manifest_id']}")
        manifest_ids.append(str(manifest["manifest_id"]))
        snapshot_end_utc = max(snapshot_end_utc or "", str(manifest.get("window_end_utc") or "")) or snapshot_end_utc
        _merge_immutable(candidates, payload.get("candidate_episode_facts", []), "candidate_id", "candidate")
        _merge_immutable(contexts, payload.get("trend_location_range_context_facts", []), "candidate_id", "context")
        _merge_immutable(outcomes, payload.get("rule_baseline_outcome_facts", []), "outcome_id", "outcome")
    return {
        "manifest_ids": sorted(manifest_ids),
        "snapshot_end_utc": snapshot_end_utc,
        "candidates": candidates,
        "contexts": contexts,
        "outcomes": outcomes,
    }


def _metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["realized_net_r"]) for row in rows if row.get("realized_net_r") is not None]
    return {
        "independent_episode_count": len(rows),
        "priced_episode_count": len(values),
        "positive_net_r_count": sum(value > 0 for value in values),
        "positive_net_r_rate": round(sum(value > 0 for value in values) / len(values), 6) if values else None,
        "average_net_r": round(statistics.fmean(values), 6) if values else None,
        "median_net_r": round(statistics.median(values), 6) if values else None,
        "minimum_net_r": round(min(values), 6) if values else None,
        "maximum_net_r": round(max(values), 6) if values else None,
        "small_sample": len(values) < 30,
    }


def _eligible_row(
    candidate: dict[str, Any],
    context: dict[str, Any],
    outcome: dict[str, Any],
    campaign: dict[str, Any],
    approval_time: str,
    evaluated_at: str,
) -> dict[str, Any] | None:
    population = campaign["population"]
    if candidate.get("decision_time_utc", "") <= approval_time:
        return None
    if candidate.get("decision_time_utc", "") > evaluated_at or outcome.get("observed_at_utc", "") > evaluated_at:
        return None
    if not context.get("as_of_utc") or context.get("as_of_utc", "") > candidate.get("decision_time_utc", ""):
        return None
    if candidate.get("instrument") != campaign["instrument"]:
        return None
    if candidate.get("mechanism_class") != "OBJECTIVE_LEVEL_FAILED_AUCTION":
        return None
    if candidate.get("base_timeframe") != population["timeframe"]:
        return None
    if candidate.get("level_signature") not in set(population["allowed_levels"]):
        return None
    if outcome.get("entry_model") != population["entry_model"]:
        return None
    if outcome.get("horizon_bars") != population["outcome_horizon_m15_bars"]:
        return None
    if outcome.get("same_bar_tie_policy") != population["same_bar_tie_policy"]:
        return None
    if outcome.get("arm_id") != "RULE_BASELINE":
        return None
    if outcome.get("candidate_id") != candidate.get("candidate_id"):
        return None
    if context.get("candidate_id") != candidate.get("candidate_id"):
        return None

    daily = context.get("daily_trend") if isinstance(context.get("daily_trend"), dict) else {}
    room = context.get("target_room") if isinstance(context.get("target_room"), dict) else {}
    threshold = float(campaign["exact_specification"]["objective_room"]["minimum_reward_room_r"])
    aligned = daily.get("status") == "READY" and daily.get("direction_alignment") == "ALIGNED"
    room_value = room.get("reward_room_r")
    enough_room = room.get("status") == "READY" and isinstance(room_value, (int, float)) and float(room_value) >= threshold
    return {
        "episode_id": candidate["episode_id"],
        "candidate_id": candidate["candidate_id"],
        "decision_time_utc": candidate["decision_time_utc"],
        "outcome_id": outcome["outcome_id"],
        "observed_at_utc": outcome["observed_at_utc"],
        "outcome_source": outcome["outcome_source"],
        "realized_net_r": outcome.get("realized_net_r"),
        "cohort": "TREATMENT" if aligned and enough_room else "COMPARATOR",
        "daily_direction_aligned": aligned,
        "reward_room_r": room_value,
    }


def build_evaluation(
    connection,
    campaign_id: str,
    inbox_dir: Path,
    *,
    evaluated_at_utc: str | None = None,
) -> dict[str, Any]:
    if campaign_state(connection, campaign_id) != "APPROVED":
        raise ValueError("campaign evaluation requires explicit human approval")
    readiness = campaign_data_readiness(connection, campaign_id)
    if readiness["missing_data_classes"]:
        raise ValueError(f"campaign required data is unavailable: {readiness['missing_data_classes']}")
    row = connection.execute(
        "SELECT payload_json FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
    ).fetchone()
    experiment_row = connection.execute(
        "SELECT experiment_id, payload_json, predeclared_at_utc FROM experiment_specs WHERE experiment_id=?",
        (f"EXP_{campaign_id}",),
    ).fetchone()
    if row is None or experiment_row is None:
        raise ValueError("approved campaign has no sealed experiment specification")
    campaign = json.loads(row["payload_json"])
    experiment = json.loads(experiment_row["payload_json"])
    requested_evaluation_time = evaluated_at_utc or utc_now()
    approval_time = str(experiment["approved_at_utc"])
    evidence = _load_evidence(connection, inbox_dir, campaign["instrument"])
    snapshot_end = evidence["snapshot_end_utc"] or requested_evaluation_time
    evidence_cutoff = min(requested_evaluation_time, snapshot_end)
    evaluated_at = max(approval_time, evidence_cutoff)

    outcome_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for outcome in evidence["outcomes"].values():
        outcome_by_candidate.setdefault(str(outcome.get("candidate_id")), []).append(outcome)
    eligible: list[dict[str, Any]] = []
    for candidate_id, candidate in evidence["candidates"].items():
        context = evidence["contexts"].get(candidate_id)
        if context is None:
            continue
        for outcome in sorted(
            outcome_by_candidate.get(candidate_id, []),
            key=lambda value: (str(value.get("observed_at_utc") or ""), str(value.get("outcome_id") or "")),
        ):
            built = _eligible_row(candidate, context, outcome, campaign, approval_time, evidence_cutoff)
            if built is not None:
                eligible.append(built)
                break

    first_per_episode: dict[str, dict[str, Any]] = {}
    for record in sorted(
        eligible,
        key=lambda value: (value["decision_time_utc"], value["candidate_id"], value["outcome_id"]),
    ):
        first_per_episode.setdefault(str(record["episode_id"]), record)
    independent = list(first_per_episode.values())
    sources = sorted({str(record["outcome_source"]) for record in independent})
    source_reports = []
    minimum_treatment = int(campaign["review_gates"]["minimum_resolved_independent_treatment_episodes"])
    minimum_comparator = int(campaign["review_gates"]["minimum_resolved_independent_comparator_episodes"])
    for source in sources:
        source_rows = [record for record in independent if record["outcome_source"] == source]
        treatment = [record for record in source_rows if record["cohort"] == "TREATMENT"]
        comparator = [record for record in source_rows if record["cohort"] == "COMPARATOR"]
        treatment_metrics = _metric_summary(treatment)
        comparator_metrics = _metric_summary(comparator)
        lift = None
        if treatment_metrics["average_net_r"] is not None and comparator_metrics["average_net_r"] is not None:
            lift = round(treatment_metrics["average_net_r"] - comparator_metrics["average_net_r"], 6)
        gates_met = (
            treatment_metrics["priced_episode_count"] >= minimum_treatment
            and comparator_metrics["priced_episode_count"] >= minimum_comparator
        )
        source_reports.append(
            {
                "outcome_source": source,
                "treatment": treatment_metrics,
                "comparator": comparator_metrics,
                "average_net_r_lift": lift,
                "sample_gates_met": gates_met,
                "result_interpretation": "READY_FOR_HUMAN_REVIEW" if gates_met else "ACCRUING_NO_CONCLUSION",
            }
        )
    return {
        "schema": "FX_RESEARCH_EXPERIMENT_EVALUATION_V1",
        "campaign_id": campaign_id,
        "experiment_id": experiment_row["experiment_id"],
        "campaign_payload_hash": experiment["campaign_payload_hash"],
        "predeclared_at_utc": approval_time,
        "evaluated_at_utc": evaluated_at,
        "evidence_cutoff_utc": evidence_cutoff,
        "confirmatory_cutover_policy": "CANDIDATE_DECISION_TIME_STRICTLY_AFTER_HUMAN_APPROVAL",
        "legacy_preapproval_evidence_excluded": True,
        "evidence_manifest_ids": evidence["manifest_ids"],
        "eligible_candidate_count_before_episode_deduplication": len(eligible),
        "independent_episode_count": len(independent),
        "outcome_sources_pooled": False,
        "source_reports": source_reports,
        "review_status": (
            "READY_FOR_HUMAN_REVIEW"
            if any(report["sample_gates_met"] for report in source_reports)
            else "ACCRUING_NO_CONCLUSION"
        ),
        "automatic_promotion_allowed": False,
        "downstream_authority": "NONE",
    }


def run_campaign(
    connection,
    campaign_id: str,
    inbox_dir: Path,
    *,
    evaluated_at_utc: str | None = None,
) -> dict[str, Any]:
    evaluation = build_evaluation(
        connection,
        campaign_id,
        inbox_dir,
        evaluated_at_utc=evaluated_at_utc,
    )
    evidence_identity = {
        "experiment_id": evaluation["experiment_id"],
        "predeclared_at_utc": evaluation["predeclared_at_utc"],
        "evidence_manifest_ids": evaluation["evidence_manifest_ids"],
    }
    run_id = f"RUN_{payload_hash(evidence_identity)[:24]}"
    run_payload = {**evaluation, "run_id": run_id}
    inserted = insert_immutable(
        connection,
        "experiment_runs",
        "run_id",
        run_id,
        run_payload,
        {"experiment_id": evaluation["experiment_id"], "started_at_utc": evaluation["evaluated_at_utc"]},
    )
    for source_report in evaluation["source_reports"]:
        finding = {
            "schema": "FX_RESEARCH_FINDING_V1",
            "run_id": run_id,
            "campaign_id": campaign_id,
            "experiment_id": evaluation["experiment_id"],
            "predeclared_at_utc": evaluation["predeclared_at_utc"],
            "outcome_sources_pooled": False,
            **source_report,
            "automatic_promotion_allowed": False,
        }
        insert_immutable(
            connection,
            "findings",
            "finding_id",
            f"FINDING_{payload_hash(finding)[:24]}",
            finding,
            {"run_id": run_id, "knowable_at_utc": evaluation["evaluated_at_utc"]},
        )
    return {**run_payload, "inserted": inserted}


def experiment_report(connection, campaign_id: str) -> dict[str, Any]:
    experiment_id = f"EXP_{campaign_id}"
    row = connection.execute(
        "SELECT payload_json FROM experiment_runs WHERE experiment_id=? ORDER BY started_at_utc DESC, run_id DESC LIMIT 1",
        (experiment_id,),
    ).fetchone()
    return {
        "campaign_id": campaign_id,
        "experiment_id": experiment_id,
        "campaign_state": campaign_state(connection, campaign_id),
        "latest_evaluation": json.loads(row["payload_json"]) if row else None,
        "automatic_promotion_allowed": False,
    }
