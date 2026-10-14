from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .campaigns import campaign_state
from .storage import insert_immutable


SCHEMA = "FX_RESEARCH_BATCH_V1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_batch(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError("unsupported research batch schema")
    if not 1 <= int(payload.get("maximum_active_campaigns", 0)) <= 3:
        raise ValueError("research batch active campaign cap must be between one and three")
    campaigns = payload.get("campaign_ids")
    if not isinstance(campaigns, list) or len(campaigns) > int(payload["maximum_active_campaigns"]):
        raise ValueError("research batch campaign membership exceeds its locked cap")
    multiplicity = payload.get("multiplicity_policy") if isinstance(payload.get("multiplicity_policy"), dict) else {}
    if multiplicity.get("method") != "HOLM_BONFERRONI":
        raise ValueError("research batch requires the locked Holm-Bonferroni policy")
    if int(multiplicity.get("hypothesis_budget", 0)) != int(payload["maximum_active_campaigns"]):
        raise ValueError("multiplicity hypothesis budget must equal the campaign cap")
    authority = payload.get("authority") if isinstance(payload.get("authority"), dict) else {}
    if any(authority.get(key) is not False for key in (
        "automatic_campaign_addition",
        "automatic_approval",
        "automatic_promotion",
        "downstream_authority",
    )):
        raise ValueError("research batch authority must remain inert")
    return payload


def register_batch(connection, path: Path) -> dict[str, Any]:
    payload = load_batch(path)
    for campaign_id in payload["campaign_ids"]:
        if connection.execute(
            "SELECT 1 FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone() is None:
            raise ValueError(f"research batch references unknown campaign: {campaign_id}")
    inserted = insert_immutable(
        connection,
        "research_batches",
        "batch_id",
        payload["batch_id"],
        payload,
        {"created_at_utc": payload["created_at_utc"]},
    )
    for campaign_id in payload["campaign_ids"]:
        membership = {
            "schema": "FX_RESEARCH_BATCH_MEMBERSHIP_V1",
            "batch_id": payload["batch_id"],
            "campaign_id": campaign_id,
            "added_at_utc": payload["created_at_utc"],
            "added_by": "HUMAN_REVIEWED_BATCH_SPEC",
        }
        insert_immutable(
            connection,
            "batch_campaigns",
            "membership_id",
            f"{payload['batch_id']}:{campaign_id}",
            membership,
            {
                "batch_id": payload["batch_id"],
                "campaign_id": campaign_id,
                "added_at_utc": payload["created_at_utc"],
            },
        )
    return {
        "batch_id": payload["batch_id"],
        "inserted": inserted,
        "campaign_count": len(payload["campaign_ids"]),
        "available_slot_count": int(payload["maximum_active_campaigns"]) - len(payload["campaign_ids"]),
        "automatic_campaign_addition": False,
    }


def batch_report(connection) -> dict[str, Any]:
    batches = []
    for row in connection.execute(
        "SELECT batch_id, payload_json FROM research_batches ORDER BY created_at_utc, batch_id"
    ).fetchall():
        payload = json.loads(row["payload_json"])
        memberships = connection.execute(
            "SELECT campaign_id FROM batch_campaigns WHERE batch_id=? ORDER BY added_at_utc, campaign_id",
            (row["batch_id"],),
        ).fetchall()
        campaigns = [
            {"campaign_id": member["campaign_id"], "state": campaign_state(connection, member["campaign_id"])}
            for member in memberships
        ]
        maximum = int(payload["maximum_active_campaigns"])
        alpha = float(payload["multiplicity_policy"]["familywise_alpha"])
        occupied = len(campaigns)
        batches.append(
            {
                "batch_id": row["batch_id"],
                "title": payload["title"],
                "instrument": payload["instrument"],
                "maximum_active_campaigns": maximum,
                "occupied_slot_count": occupied,
                "available_slot_count": maximum - occupied,
                "campaigns": campaigns,
                "multiplicity_policy": payload["multiplicity_policy"],
                "most_conservative_adjusted_alpha": round(alpha / maximum, 8),
                "automatic_campaign_addition": False,
            }
        )
    return {"batch_count": len(batches), "batches": batches}


def add_campaign_to_batch(
    connection,
    batch_id: str,
    campaign_id: str,
    *,
    added_by: str,
    reason: str,
    added_at_utc: str | None = None,
) -> dict[str, Any]:
    batch_row = connection.execute(
        "SELECT payload_json FROM research_batches WHERE batch_id=?", (batch_id,)
    ).fetchone()
    if batch_row is None:
        raise ValueError("unknown research batch")
    if campaign_state(connection, campaign_id) != "APPROVED":
        raise ValueError("only an explicitly approved campaign can enter a confirmatory batch")
    if not added_by.strip() or added_by.upper() in {"SYSTEM", "AGENT", "AUTOMATION"}:
        raise ValueError("batch addition requires a named human")
    if not reason.strip():
        raise ValueError("batch addition requires a reason")
    batch = json.loads(batch_row["payload_json"])
    existing = connection.execute(
        "SELECT campaign_id FROM batch_campaigns WHERE batch_id=?", (batch_id,)
    ).fetchall()
    existing_ids = {str(row["campaign_id"]) for row in existing}
    if campaign_id in existing_ids:
        return {
            "batch_id": batch_id,
            "campaign_id": campaign_id,
            "inserted": False,
            "occupied_slot_count": len(existing_ids),
            "available_slot_count": int(batch["maximum_active_campaigns"]) - len(existing_ids),
            "automatic_addition": False,
        }
    maximum = int(batch["maximum_active_campaigns"])
    if len(existing_ids) >= maximum:
        raise ValueError("research batch has no available confirmatory slot")
    occurred_at = added_at_utc or utc_now()
    membership = {
        "schema": "FX_RESEARCH_BATCH_MEMBERSHIP_V1",
        "batch_id": batch_id,
        "campaign_id": campaign_id,
        "added_at_utc": occurred_at,
        "added_by": added_by,
        "reason": reason,
        "automatic_addition": False,
    }
    inserted = insert_immutable(
        connection,
        "batch_campaigns",
        "membership_id",
        f"{batch_id}:{campaign_id}",
        membership,
        {
            "batch_id": batch_id,
            "campaign_id": campaign_id,
            "added_at_utc": occurred_at,
        },
    )
    occupied = len(existing_ids) + int(inserted)
    return {
        "batch_id": batch_id,
        "campaign_id": campaign_id,
        "inserted": inserted,
        "occupied_slot_count": occupied,
        "available_slot_count": maximum - occupied,
        "automatic_addition": False,
    }


def active_slot_count(connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS n FROM batch_campaigns").fetchone()
    return int(row["n"] if row else 0)
