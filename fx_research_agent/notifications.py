from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from .storage import insert_immutable, payload_hash


WEBHOOK_ENV = "FX_RESEARCH_DISCORD_WEBHOOK_URL"
Transport = Callable[[str, str], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _discord_transport(webhook_url: str, message: str) -> None:
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps({"content": message}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "fx-research-agent/1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status not in {200, 204}:
            raise RuntimeError(f"Discord webhook returned HTTP {response.status}")


def notify_once(
    connection,
    *,
    event_type: str,
    subject_id: str,
    message: str,
    webhook_url: str | None = None,
    transport: Transport | None = None,
    sent_at_utc: str | None = None,
) -> dict[str, Any]:
    identity = {"event_type": event_type, "subject_id": subject_id}
    notification_id = "NOTICE_" + payload_hash(identity)[:24]
    existing = connection.execute(
        "SELECT notification_id FROM research_notifications WHERE notification_id=?",
        (notification_id,),
    ).fetchone()
    if existing:
        return {"notification_id": notification_id, "status": "ALREADY_SENT"}
    target = webhook_url if webhook_url is not None else os.environ.get(WEBHOOK_ENV, "")
    if not target.strip():
        return {"notification_id": notification_id, "status": "DISABLED_NO_WEBHOOK"}
    try:
        (transport or _discord_transport)(target, message)
    except Exception as exc:  # Notification delivery must not stop deterministic research jobs.
        return {
            "notification_id": notification_id,
            "status": "DELIVERY_FAILED",
            "error": str(exc),
        }
    sent_at = sent_at_utc or utc_now()
    payload = {
        "schema": "FX_RESEARCH_NOTIFICATION_V1",
        "notification_id": notification_id,
        "event_type": event_type,
        "subject_id": subject_id,
        "message": message,
        "sent_at_utc": sent_at,
    }
    insert_immutable(
        connection,
        "research_notifications",
        "notification_id",
        notification_id,
        payload,
        {"event_type": event_type, "subject_id": subject_id, "sent_at_utc": sent_at},
    )
    return {"notification_id": notification_id, "status": "SENT"}


def notify_ingest_failures(connection, pipeline: str, sync_result: dict[str, Any]) -> list[dict[str, Any]]:
    notifications = []
    for failure in sync_result.get("rejected", []):
        manifest = str(failure.get("manifest") or "unknown")
        error = str(failure.get("error") or "unknown error")
        subject_id = f"{pipeline}:{manifest}:{payload_hash(error)[:12]}"
        notifications.append(
            notify_once(
                connection,
                event_type="INGEST_FAILED",
                subject_id=subject_id,
                message=(
                    "FX Research: ingest needs attention\n"
                    f"Pipeline: {pipeline}\n"
                    f"Manifest: {manifest.rsplit('/', 1)[-1]}\n"
                    f"Error: {error[:500]}\n"
                    "State: fail-closed; no research authority changed"
                ),
            )
        )
    return notifications


def notify_gate_crossings(connection, refresh_result: dict[str, Any]) -> list[dict[str, Any]]:
    notifications = []
    for campaign in refresh_result.get("campaigns", []):
        if campaign.get("sample_gate_crossed_now") is not True:
            continue
        campaign_id = str(campaign["campaign_id"])
        notifications.append(
            notify_once(
                connection,
                event_type="SAMPLE_GATE_REACHED",
                subject_id=campaign_id,
                message=(
                    "FX Research: sample gate reached\n"
                    f"Campaign: {campaign_id}\n"
                    f"Independent episodes: {campaign.get('independent_episode_count')}\n"
                    "Action: human review required\n"
                    "Trading authority: none"
                ),
            )
        )
    return notifications


def notify_proposals_for_review(connection, proposal_result: dict[str, Any]) -> list[dict[str, Any]]:
    notifications = []
    for result in proposal_result.get("results", []):
        if result.get("status") != "ACCEPTED_PROPOSED" or not result.get("hypothesis_id"):
            continue
        hypothesis_id = str(result["hypothesis_id"])
        row = connection.execute(
            "SELECT payload_json FROM hypotheses WHERE hypothesis_id=?", (hypothesis_id,)
        ).fetchone()
        hypothesis = json.loads(row["payload_json"]) if row else {}
        notifications.append(
            notify_once(
                connection,
                event_type="PROPOSAL_REVIEW_REQUIRED",
                subject_id=hypothesis_id,
                message=(
                    "FX Research: proposal needs review\n"
                    f"Hypothesis: {hypothesis_id}\n"
                    f"Mechanism: {hypothesis.get('mechanism_class', 'unknown')}\n"
                    f"Idea: {str(hypothesis.get('statement', ''))[:600]}\n"
                    "No campaign was created or approved"
                ),
            )
        )
    return notifications


def notification_status(connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT event_type, COUNT(*) AS n FROM research_notifications GROUP BY event_type"
    ).fetchall()
    return {
        "schema": "FX_RESEARCH_NOTIFICATION_STATUS_V1",
        "webhook_configured": bool(os.environ.get(WEBHOOK_ENV, "").strip()),
        "sent_count": sum(int(row["n"]) for row in rows),
        "sent_by_event_type": {str(row["event_type"]): int(row["n"]) for row in rows},
        "normal_refresh_notifications": False,
        "order_authority": False,
    }
