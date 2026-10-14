from __future__ import annotations

import gzip
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .campaigns import campaign_data_readiness, campaign_state
from .evidence import load_validated_package
from .market_data import resolve_payload_path, validate_manifest as validate_market_manifest
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


def _read_json_payload(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_market_spread_bars(
    connection,
    inbox_dir: Path,
    instrument: str,
) -> dict[str, Any]:
    samples: dict[str, dict[str, Any]] = {}
    manifest_ids: list[str] = []
    for row in connection.execute(
        "SELECT payload_json FROM market_data_manifests WHERE usable_for_testing=1 ORDER BY registered_at_utc, manifest_id"
    ).fetchall():
        registered = json.loads(row["payload_json"])
        if registered.get("instrument") != instrument:
            continue
        manifest_path = inbox_dir / f"{registered['manifest_id']}.manifest.json"
        if not manifest_path.is_file():
            matches = list(inbox_dir.glob(f"*{registered['manifest_id']}*.manifest.json"))
            if len(matches) != 1:
                raise ValueError(
                    f"immutable market manifest unavailable in inbox: {registered['manifest_id']}"
                )
            manifest_path = matches[0]
        manifest = validate_market_manifest(manifest_path)
        if manifest != registered:
            raise ValueError(
                f"registered market manifest differs from inbox copy: {manifest['manifest_id']}"
            )
        manifest_ids.append(str(manifest["manifest_id"]))
        payload = _read_json_payload(resolve_payload_path(manifest_path, manifest))
        for sample in payload.get("spread_samples", []):
            if not isinstance(sample, dict) or sample.get("instrument") != instrument:
                continue
            sample_time = str(sample.get("sample_time_utc") or "")
            if not sample_time or not isinstance(sample.get("spread_pips"), (int, float)):
                continue
            existing = samples.get(sample_time)
            if existing is not None and canonical_json(existing) != canonical_json(sample):
                raise ValueError(f"conflicting immutable spread sample rewrite: {sample_time}")
            samples[sample_time] = sample

    by_bar: dict[str, list[float]] = {}
    for sample_time, sample in samples.items():
        stamp = datetime.fromisoformat(sample_time.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
        minute = (stamp.minute // 15) * 15
        bar_start = stamp.replace(minute=minute, second=0, microsecond=0)
        bar_end = bar_start + timedelta(minutes=15)
        key = bar_end.isoformat().replace("+00:00", "Z")
        by_bar.setdefault(key, []).append(float(sample["spread_pips"]))
    return {
        "manifest_ids": sorted(manifest_ids),
        "bar_medians": {
            key: float(statistics.median(values)) for key, values in by_bar.items()
        },
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


def _canonical_level_type(value: Any) -> str:
    return str(value or "").strip().upper().replace("NEW_YORK_SESSION_", "NY_SESSION_")


def _candidate_levels_allowed(candidate: dict[str, Any], allowed_levels: list[Any]) -> bool:
    allowed = {_canonical_level_type(value) for value in allowed_levels}
    signature = str(candidate.get("level_signature") or "")
    observed = {
        _canonical_level_type(value)
        for value in signature.split(",")
        if str(value).strip()
    }
    return bool(observed) and observed.issubset(allowed)


def _common_eligible_row(
    candidate: dict[str, Any],
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
    if candidate.get("instrument") != campaign["instrument"]:
        return None
    if candidate.get("mechanism_class") != "OBJECTIVE_LEVEL_FAILED_AUCTION":
        return None
    if candidate.get("base_timeframe") != population["timeframe"]:
        return None
    if not _candidate_levels_allowed(candidate, population["allowed_levels"]):
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
    return {
        "episode_id": candidate["episode_id"],
        "candidate_id": candidate["candidate_id"],
        "decision_time_utc": candidate["decision_time_utc"],
        "outcome_id": outcome["outcome_id"],
        "observed_at_utc": outcome["observed_at_utc"],
        "outcome_source": outcome["outcome_source"],
        "realized_net_r": outcome.get("realized_net_r"),
    }


def _classify_trend_location_range(
    row: dict[str, Any],
    candidate: dict[str, Any],
    context: dict[str, Any] | None,
    campaign: dict[str, Any],
) -> dict[str, Any] | None:
    if context is None or context.get("candidate_id") != candidate.get("candidate_id"):
        return None
    if not context.get("as_of_utc") or context.get("as_of_utc", "") > candidate.get(
        "decision_time_utc", ""
    ):
        return None
    daily = context.get("daily_trend") if isinstance(context.get("daily_trend"), dict) else {}
    room = context.get("target_room") if isinstance(context.get("target_room"), dict) else {}
    threshold = float(
        campaign["exact_specification"]["objective_room"]["minimum_reward_room_r"]
    )
    aligned = (
        daily.get("status") == "READY"
        and daily.get("direction_alignment") == "ALIGNED"
    )
    room_value = room.get("reward_room_r")
    enough_room = (
        room.get("status") == "READY"
        and isinstance(room_value, (int, float))
        and float(room_value) >= threshold
    )
    return {
        **row,
        "cohort": "TREATMENT" if aligned and enough_room else "COMPARATOR",
        "cohort_label": (
            "ALIGNED_AND_ROOM_GE_THRESHOLD"
            if aligned and enough_room
            else "COMPLEMENT"
        ),
        "daily_direction_aligned": aligned,
        "reward_room_r": room_value,
    }


def _classify_spread_degradation(
    row: dict[str, Any],
    candidate: dict[str, Any],
    campaign: dict[str, Any],
    spread_bar_medians: dict[str, float],
) -> dict[str, Any] | None:
    market = (
        candidate.get("market_facts")
        if isinstance(candidate.get("market_facts"), dict)
        else {}
    )
    decision_spread = market.get("spread_pips")
    if not isinstance(decision_spread, (int, float)):
        return None
    specification = campaign["exact_specification"]
    lookback = int(specification["spread_context"]["trailing_completed_m15_bars"])
    threshold = float(specification["spread_context"]["high_spread_ratio_threshold"])
    decision_time = str(candidate["decision_time_utc"])
    prior_values = [
        value
        for bar_end, value in sorted(spread_bar_medians.items())
        if bar_end < decision_time
    ][-lookback:]
    if len(prior_values) < lookback:
        return None
    trailing_median = float(statistics.median(prior_values))
    if trailing_median <= 0:
        return None
    ratio = float(decision_spread) / trailing_median
    high_spread = ratio > threshold
    return {
        **row,
        "cohort": "TREATMENT" if high_spread else "COMPARATOR",
        "cohort_label": "HIGH_SPREAD" if high_spread else "NORMAL_SPREAD",
        "decision_spread_pips": round(float(decision_spread), 6),
        "trailing_spread_median_pips": round(trailing_median, 6),
        "spread_ratio": round(ratio, 6),
        "spread_lookback_bar_count": len(prior_values),
    }


def _classify_touch_degradation(
    row: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    levels = candidate.get("objective_levels")
    if not isinstance(levels, list):
        return None
    indices = [
        int(level["touch_index"])
        for level in levels
        if isinstance(level, dict)
        and isinstance(level.get("touch_index"), int)
        and int(level["touch_index"]) >= 1
    ]
    if not indices:
        return None
    maximum_touch_index = max(indices)
    first_touch = maximum_touch_index == 1
    return {
        **row,
        "cohort": "TREATMENT" if first_touch else "COMPARATOR",
        "cohort_label": "FIRST_TOUCH" if first_touch else "REPEAT_TOUCH",
        "maximum_contributing_touch_index": maximum_touch_index,
    }


def _eligible_row(
    candidate: dict[str, Any],
    context: dict[str, Any] | None,
    outcome: dict[str, Any],
    campaign: dict[str, Any],
    approval_time: str,
    evaluated_at: str,
    spread_bar_medians: dict[str, float],
) -> dict[str, Any] | None:
    row = _common_eligible_row(
        candidate,
        outcome,
        campaign,
        approval_time,
        evaluated_at,
    )
    if row is None:
        return None
    classifier = str(
        campaign.get("exact_specification", {})
        .get("cohort_rule", {})
        .get("type")
        or "TREND_ALIGNMENT_AND_OBJECTIVE_ROOM"
    )
    if classifier == "TREND_ALIGNMENT_AND_OBJECTIVE_ROOM":
        return _classify_trend_location_range(row, candidate, context, campaign)
    if classifier == "DECISION_SPREAD_TO_TRAILING_MEDIAN":
        return _classify_spread_degradation(
            row,
            candidate,
            campaign,
            spread_bar_medians,
        )
    if classifier == "MAXIMUM_CONTRIBUTING_TOUCH_INDEX":
        return _classify_touch_degradation(row, candidate)
    raise ValueError(f"unsupported campaign cohort rule: {classifier}")


def build_evaluation(
    connection,
    campaign_id: str,
    evidence_inbox_dir: Path,
    *,
    market_inbox_dir: Path | None = None,
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
    evidence = _load_evidence(
        connection,
        evidence_inbox_dir,
        campaign["instrument"],
    )
    market = (
        _load_market_spread_bars(
            connection,
            market_inbox_dir,
            campaign["instrument"],
        )
        if market_inbox_dir is not None
        else {"manifest_ids": [], "bar_medians": {}}
    )
    snapshot_end = evidence["snapshot_end_utc"] or requested_evaluation_time
    evidence_cutoff = min(requested_evaluation_time, snapshot_end)
    evaluated_at = max(approval_time, evidence_cutoff)

    outcome_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for outcome in evidence["outcomes"].values():
        outcome_by_candidate.setdefault(str(outcome.get("candidate_id")), []).append(outcome)
    eligible: list[dict[str, Any]] = []
    for candidate_id, candidate in evidence["candidates"].items():
        context = evidence["contexts"].get(candidate_id)
        for outcome in sorted(
            outcome_by_candidate.get(candidate_id, []),
            key=lambda value: (str(value.get("observed_at_utc") or ""), str(value.get("outcome_id") or "")),
        ):
            built = _eligible_row(
                candidate,
                context,
                outcome,
                campaign,
                approval_time,
                evidence_cutoff,
                market["bar_medians"],
            )
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
        "market_data_manifest_ids": market["manifest_ids"],
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
    evidence_inbox_dir: Path,
    *,
    market_inbox_dir: Path | None = None,
    evaluated_at_utc: str | None = None,
) -> dict[str, Any]:
    evaluation = build_evaluation(
        connection,
        campaign_id,
        evidence_inbox_dir,
        market_inbox_dir=market_inbox_dir,
        evaluated_at_utc=evaluated_at_utc,
    )
    evidence_identity = {
        "experiment_id": evaluation["experiment_id"],
        "predeclared_at_utc": evaluation["predeclared_at_utc"],
        "evidence_manifest_ids": evaluation["evidence_manifest_ids"],
        "market_data_manifest_ids": evaluation["market_data_manifest_ids"],
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
