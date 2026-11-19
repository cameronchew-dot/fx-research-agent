from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .storage import insert_immutable, payload_hash


ALLOWED_DECISIONS = {
    "CONTINUE_CONFIRMATORY",
    "PARK",
    "REJECT",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def latest_campaign_review(connection, campaign_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT review_id, payload_json FROM campaign_reviews "
        "WHERE campaign_id=? ORDER BY reviewed_at_utc DESC, review_id DESC LIMIT 1",
        (campaign_id,),
    ).fetchone()
    if row is None:
        return None
    return {**json.loads(row["payload_json"]), "review_id": str(row["review_id"])}


def review_campaign(
    connection,
    campaign_id: str,
    *,
    decision: str,
    reviewed_by: str,
    reason: str,
    reviewed_at_utc: str | None = None,
) -> dict[str, Any]:
    normalized_decision = str(decision).upper()
    if normalized_decision not in ALLOWED_DECISIONS:
        raise ValueError(f"unsupported campaign review decision: {decision}")
    if not reviewed_by.strip() or not reason.strip():
        raise ValueError("campaign review requires reviewed_by and reason")

    campaign = connection.execute(
        "SELECT campaign_id FROM research_campaigns WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()
    if campaign is None:
        raise ValueError(f"unknown campaign: {campaign_id}")

    run = connection.execute(
        "SELECT run_id, payload_json FROM experiment_runs "
        "WHERE experiment_id=? ORDER BY started_at_utc DESC, run_id DESC LIMIT 1",
        (f"EXP_{campaign_id}",),
    ).fetchone()
    if run is None:
        raise ValueError("campaign has no completed evaluation to review")
    evaluation = json.loads(run["payload_json"])
    if evaluation.get("review_status") != "READY_FOR_HUMAN_REVIEW":
        raise ValueError("latest campaign evaluation is not ready for human review")

    reviewed_at = reviewed_at_utc or utc_now()
    review = {
        "schema": "FX_RESEARCH_CAMPAIGN_REVIEW_V1",
        "campaign_id": campaign_id,
        "run_id": str(run["run_id"]),
        "reviewed_at_utc": reviewed_at,
        "reviewed_by": reviewed_by,
        "decision": normalized_decision,
        "reason": reason,
        "evidence_snapshot": {
            "evaluated_at_utc": evaluation.get("evaluated_at_utc"),
            "evidence_cutoff_utc": evaluation.get("evidence_cutoff_utc"),
            "independent_episode_count": evaluation.get("independent_episode_count"),
            "source_reports": evaluation.get("source_reports", []),
        },
        "confirmatory_cutover_at_utc": (
            reviewed_at if normalized_decision == "CONTINUE_CONFIRMATORY" else None
        ),
        "automatic_promotion_allowed": False,
        "downstream_authority": "NONE",
        "execution_authority": False,
    }
    review_id = f"CAMPAIGN_REVIEW_{payload_hash(review)[:24]}"
    inserted = insert_immutable(
        connection,
        "campaign_reviews",
        "review_id",
        review_id,
        review,
        {
            "campaign_id": campaign_id,
            "run_id": str(run["run_id"]),
            "decision": normalized_decision,
            "reviewed_at_utc": reviewed_at,
            "reviewed_by": reviewed_by,
        },
    )
    return {**review, "review_id": review_id, "inserted": inserted}
