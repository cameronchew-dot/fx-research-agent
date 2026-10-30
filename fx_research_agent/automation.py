from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .campaigns import campaign_data_readiness, campaign_instruments, campaign_state
from .batches import active_slot_count
from .experiments import build_evaluation, run_campaign
from .storage import insert_immutable, payload_hash


POLICY_SCHEMA = "FX_RESEARCH_AUTONOMY_POLICY_V1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_policy(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != POLICY_SCHEMA:
        raise ValueError("unsupported research autonomy policy schema")
    if not 1 <= int(payload.get("campaign_slot_limit", 0)) <= 10:
        raise ValueError("research autonomy policy campaign cap must be between one and ten")
    if int(payload.get("maximum_proposals_per_cycle", 0)) > 3:
        raise ValueError("proposal cycle cannot create more than three candidates")
    if int(payload.get("maximum_pending_machine_proposals", 0)) != 3:
        raise ValueError("pending machine proposal cap must remain three")
    if payload.get("provider") != "ANTHROPIC":
        raise ValueError("research proposals must use the governed Anthropic provider")
    if payload.get("endpoint") != "https://api.anthropic.com/v1/messages":
        raise ValueError("research proposal endpoint must be the Anthropic Messages API")
    input_policy = payload.get("proposal_input_policy") if isinstance(payload.get("proposal_input_policy"), dict) else {}
    if input_policy.get("include_findings") is not False or input_policy.get("include_net_r") is not False:
        raise ValueError("proposal input must remain blind to findings and net R")
    authority = payload.get("authority") if isinstance(payload.get("authority"), dict) else {}
    for key in (
        "automatic_campaign_creation",
        "automatic_campaign_approval",
        "automatic_policy_change",
        "automatic_downstream_export",
        "order_authority",
    ):
        if authority.get(key) is not False:
            raise ValueError(f"autonomy authority must keep {key} disabled")
    return payload


def register_policy(connection, path: Path) -> dict[str, Any]:
    payload = load_policy(path)
    inserted = insert_immutable(
        connection,
        "autonomy_policies",
        "policy_id",
        payload["policy_id"],
        payload,
        {"registered_at_utc": payload["registered_at_utc"]},
    )
    return {
        "policy_id": payload["policy_id"],
        "inserted": inserted,
        "provider": payload["provider"],
        "model": payload["model"],
        "automatic_proposals": bool(payload["authority"]["automatic_hypothesis_proposal"]),
        "automatic_approval": False,
        "order_authority": False,
    }


def current_policy(connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT payload_json FROM autonomy_policies ORDER BY registered_at_utc DESC, policy_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("research autonomy policy is not registered")
    return json.loads(row["payload_json"])


def _approved_campaign_ids(connection) -> list[str]:
    rows = connection.execute("SELECT campaign_id FROM research_campaigns ORDER BY created_at_utc, campaign_id").fetchall()
    return [str(row["campaign_id"]) for row in rows if campaign_state(connection, row["campaign_id"]) == "APPROVED"]


def _latest_progress(connection, campaign_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT payload_json FROM campaign_progress_snapshots WHERE campaign_id=? ORDER BY observed_at_utc DESC, snapshot_id DESC LIMIT 1",
        (campaign_id,),
    ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def _current_evidence_manifest_ids(connection, instruments: list[str]) -> list[str]:
    rows = connection.execute(
        "SELECT manifest_id, payload_json FROM evidence_manifests WHERE usable_for_testing=1 ORDER BY manifest_id"
    ).fetchall()
    return [
        str(row["manifest_id"])
        for row in rows
        if json.loads(row["payload_json"]).get("instrument") in instruments
    ]


def _build_progress_snapshot(
    campaign_id: str,
    evaluation: dict[str, Any],
    gate_reached: bool,
) -> dict[str, Any]:
    snapshot = {
        "schema": "FX_RESEARCH_CAMPAIGN_PROGRESS_V1",
        "campaign_id": campaign_id,
        "observed_at_utc": evaluation["evaluated_at_utc"],
        "evidence_cutoff_utc": evaluation["evidence_cutoff_utc"],
        "predeclared_at_utc": evaluation["predeclared_at_utc"],
        "evidence_manifest_ids": evaluation["evidence_manifest_ids"],
        "market_data_manifest_ids": evaluation["market_data_manifest_ids"],
        "independent_episode_count": evaluation["independent_episode_count"],
        "source_reports": evaluation["source_reports"],
        "sample_gate_reached": gate_reached,
        "automatic_promotion_allowed": False,
    }
    # Address the complete immutable snapshot. Exact refresh repeats are
    # idempotent, while any changed progress receives a distinct record ID.
    snapshot["snapshot_id"] = f"PROGRESS_{payload_hash(snapshot)[:24]}"
    return snapshot


def refresh_approved_campaigns(
    connection,
    evidence_inbox: Path,
    *,
    market_inbox: Path | None = None,
    trigger: str,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    if trigger not in {"DAILY_SCHEDULE", "EVIDENCE_SYNC_THRESHOLD_CHECK", "MANUAL"}:
        raise ValueError("unsupported evaluation refresh trigger")
    policy = current_policy(connection)
    if trigger == "EVIDENCE_SYNC_THRESHOLD_CHECK" and not policy.get("threshold_refresh_enabled"):
        raise ValueError("threshold-triggered refresh is disabled")
    observed_at = observed_at_utc or utc_now()
    campaigns = []
    for campaign_id in _approved_campaign_ids(connection):
        campaign_row = connection.execute(
            "SELECT payload_json FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        campaign = json.loads(campaign_row["payload_json"])
        readiness = campaign_data_readiness(connection, campaign_id)
        if readiness["readiness_status"] != "READY":
            campaigns.append(
                {
                    "campaign_id": campaign_id,
                    "progress_snapshot_inserted": False,
                    "independent_episode_count": 0,
                    "sample_gate_reached": False,
                    "sample_gate_crossed_now": False,
                    "evaluation_refreshed": False,
                    "run_id": None,
                    "review_status": "BLOCKED_DATA_READINESS",
                    "skip_reason": "CAMPAIGN_DATA_NOT_READY",
                    "readiness_blocks": readiness["blocks"],
                    "missing_data_classes": readiness["missing_data_classes"],
                    "missing_instruments": readiness["missing_instruments"],
                }
            )
            continue
        previous = _latest_progress(connection, campaign_id)
        current_manifest_ids = _current_evidence_manifest_ids(connection, campaign_instruments(campaign))
        if (
            trigger == "EVIDENCE_SYNC_THRESHOLD_CHECK"
            and previous is not None
            and previous.get("evidence_manifest_ids") == current_manifest_ids
        ):
            campaigns.append(
                {
                    "campaign_id": campaign_id,
                    "progress_snapshot_inserted": False,
                    "independent_episode_count": previous["independent_episode_count"],
                    "sample_gate_reached": previous["sample_gate_reached"],
                    "sample_gate_crossed_now": False,
                    "evaluation_refreshed": False,
                    "run_id": None,
                    "review_status": (
                        "READY_FOR_HUMAN_REVIEW"
                        if previous["sample_gate_reached"]
                        else "ACCRUING_NO_CONCLUSION"
                    ),
                    "skip_reason": "NO_NEW_EVIDENCE_MANIFEST",
                }
            )
            continue
        evaluation = build_evaluation(
            connection,
            campaign_id,
            evidence_inbox,
            market_inbox_dir=market_inbox,
            evaluated_at_utc=observed_at,
        )
        gate_reached = any(report["sample_gates_met"] for report in evaluation["source_reports"])
        previous_gate_reached = bool(previous and previous.get("sample_gate_reached"))
        snapshot = _build_progress_snapshot(campaign_id, evaluation, gate_reached)
        inserted = insert_immutable(
            connection,
            "campaign_progress_snapshots",
            "snapshot_id",
            snapshot["snapshot_id"],
            snapshot,
            {"campaign_id": campaign_id, "observed_at_utc": snapshot["observed_at_utc"]},
        )
        threshold_crossed = gate_reached and not previous_gate_reached
        should_evaluate = trigger in {"DAILY_SCHEDULE", "MANUAL"} or threshold_crossed
        run = (
            run_campaign(
                connection,
                campaign_id,
                evidence_inbox,
                market_inbox_dir=market_inbox,
                evaluated_at_utc=observed_at,
            )
            if should_evaluate
            else None
        )
        campaigns.append(
            {
                "campaign_id": campaign_id,
                "progress_snapshot_inserted": inserted,
                "independent_episode_count": evaluation["independent_episode_count"],
                "sample_gate_reached": gate_reached,
                "sample_gate_crossed_now": threshold_crossed,
                "evaluation_refreshed": run is not None,
                "run_id": run.get("run_id") if run else None,
                "review_status": evaluation["review_status"],
            }
        )
    return {
        "schema": "FX_RESEARCH_AUTOMATED_REFRESH_V1",
        "trigger": trigger,
        "observed_at_utc": observed_at,
        "approved_campaign_count": len(campaigns),
        "campaigns": campaigns,
        "automatic_promotion_allowed": False,
        "downstream_authority": "NONE",
    }


def automation_status(connection) -> dict[str, Any]:
    policy = current_policy(connection)
    active_campaigns = active_slot_count(connection)
    return {
        "policy_id": policy["policy_id"],
        "provider": policy["provider"],
        "model": policy["model"],
        "campaign_slot_limit": policy["campaign_slot_limit"],
        "active_campaign_count": active_campaigns,
        "available_campaign_slot_count": max(
            0, int(policy["campaign_slot_limit"]) - active_campaigns
        ),
        "proposal_cadence": policy["proposal_cadence"],
        "maximum_pending_machine_proposals": policy["maximum_pending_machine_proposals"],
        "daily_evaluation_local_time": f"{int(policy['daily_evaluation_local_hour']):02d}:{int(policy['daily_evaluation_local_minute']):02d}",
        "threshold_refresh_enabled": bool(policy["threshold_refresh_enabled"]),
        "automatic_campaign_approval": False,
        "automatic_promotion": False,
        "order_authority": False,
    }
