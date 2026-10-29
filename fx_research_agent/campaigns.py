from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import insert_immutable, payload_hash


CAMPAIGN_SCHEMA = "FX_RESEARCH_CAMPAIGN_V1"
REQUIRED_FIELDS = {
    "schema",
    "campaign_id",
    "hypothesis_id",
    "created_at_utc",
    "state",
    "title",
    "instrument",
    "mechanism_class",
    "research_question",
    "null_hypothesis",
    "required_data_classes",
    "population",
    "independence_unit",
    "exact_specification",
    "controls",
    "metrics",
    "review_gates",
    "multiple_comparisons_policy",
    "stopping_rules",
    "authority",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_campaign(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_campaign(payload)
    return payload


def validate_campaign(payload: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_FIELDS - set(payload))
    if missing:
        raise ValueError(f"campaign missing required fields: {missing}")
    if payload.get("schema") != CAMPAIGN_SCHEMA:
        raise ValueError("unsupported campaign schema")
    if payload.get("state") != "DRAFT":
        raise ValueError("new campaign specifications must begin in DRAFT")
    if not isinstance(payload.get("required_data_classes"), list) or not payload["required_data_classes"]:
        raise ValueError("campaign requires explicit data classes")
    instruments = payload.get("instruments")
    if instruments is not None:
        if not isinstance(instruments, list) or not instruments:
            raise ValueError("campaign instruments must be a non-empty list")
        if len(set(instruments)) != len(instruments) or not all(isinstance(value, str) and value for value in instruments):
            raise ValueError("campaign instruments must contain unique non-empty identifiers")
    if not isinstance(payload.get("controls"), list) or not payload["controls"]:
        raise ValueError("campaign requires at least one locked control")
    if not isinstance(payload.get("metrics"), dict) or not payload["metrics"].get("primary"):
        raise ValueError("campaign requires a primary metric")
    authority = payload.get("authority") if isinstance(payload.get("authority"), dict) else {}
    forbidden = [
        "automatic_approval",
        "automatic_execution",
        "downstream_activation",
        "order_authority",
    ]
    if any(authority.get(key) is not False for key in forbidden):
        raise ValueError("campaign authority must remain explicitly inert")


def campaign_state(connection, campaign_id: str) -> str | None:
    row = connection.execute(
        """
        SELECT state
          FROM campaign_events
         WHERE campaign_id=?
         ORDER BY occurred_at_utc DESC, event_id DESC
         LIMIT 1
        """,
        (campaign_id,),
    ).fetchone()
    return str(row["state"]) if row else None


def register_campaign(connection, path: Path) -> dict[str, Any]:
    campaign = load_campaign(path)
    if connection.execute(
        "SELECT 1 FROM hypotheses WHERE hypothesis_id=?", (campaign["hypothesis_id"],)
    ).fetchone() is None:
        raise ValueError("campaign references an unknown hypothesis")
    inserted = insert_immutable(
        connection,
        "research_campaigns",
        "campaign_id",
        campaign["campaign_id"],
        campaign,
        {"created_at_utc": campaign["created_at_utc"]},
    )
    event = {
        "event_type": "CAMPAIGN_REGISTERED",
        "campaign_id": campaign["campaign_id"],
        "state": "DRAFT",
        "campaign_payload_hash": payload_hash(campaign),
    }
    insert_immutable(
        connection,
        "campaign_events",
        "event_id",
        f"{campaign['campaign_id']}:DRAFT",
        event,
        {
            "campaign_id": campaign["campaign_id"],
            "state": "DRAFT",
            "occurred_at_utc": campaign["created_at_utc"],
            "actor": "SYSTEM_OF_RECORD",
            "reason": "IMMUTABLE_DRAFT_REGISTERED",
        },
    )
    return {
        "campaign_id": campaign["campaign_id"],
        "inserted": inserted,
        "state": campaign_state(connection, campaign["campaign_id"]),
        "campaign_payload_hash": payload_hash(campaign),
        "automatic_approval": False,
    }


def approve_campaign(
    connection,
    campaign_id: str,
    *,
    expected_payload_hash: str,
    approved_by: str,
    reason: str,
    approved_at_utc: str | None = None,
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT payload_hash, payload_json FROM research_campaigns WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()
    if row is None:
        raise ValueError("unknown campaign")
    if row["payload_hash"] != expected_payload_hash:
        raise ValueError("campaign payload hash does not match explicit approval")
    if not approved_by.strip() or approved_by.upper() in {"SYSTEM", "AGENT", "AUTOMATION"}:
        raise ValueError("approval requires a named human operator")
    if not reason.strip():
        raise ValueError("approval requires a reason")
    current = campaign_state(connection, campaign_id)
    if current != "DRAFT":
        raise ValueError(f"campaign approval requires DRAFT state, found {current}")

    campaign = json.loads(row["payload_json"])
    occurred_at = approved_at_utc or utc_now()
    experiment = {
        "schema": "FX_RESEARCH_EXPERIMENT_SPEC_V1",
        "experiment_id": f"EXP_{campaign_id}",
        "campaign_id": campaign_id,
        "hypothesis_id": campaign["hypothesis_id"],
        "instrument": campaign["instrument"],
        "instruments": campaign_instruments(campaign),
        "required_data_classes": campaign["required_data_classes"],
        "population": campaign["population"],
        "independence_unit": campaign["independence_unit"],
        "exact_specification": campaign["exact_specification"],
        "controls": campaign["controls"],
        "metrics": campaign["metrics"],
        "review_gates": campaign["review_gates"],
        "multiple_comparisons_policy": campaign["multiple_comparisons_policy"],
        "stopping_rules": campaign["stopping_rules"],
        "authority": campaign["authority"],
        "campaign_payload_hash": expected_payload_hash,
        "approved_by": approved_by,
        "approved_at_utc": occurred_at,
    }
    experiment_id = experiment["experiment_id"]
    insert_immutable(
        connection,
        "experiment_specs",
        "experiment_id",
        experiment_id,
        experiment,
        {
            "hypothesis_id": campaign["hypothesis_id"],
            "predeclared_at_utc": occurred_at,
        },
    )
    for control in campaign["controls"]:
        control_id = f"{experiment_id}:{control['control_id']}"
        insert_immutable(
            connection,
            "experiment_controls",
            "control_id",
            control_id,
            {**control, "experiment_id": experiment_id},
            {"experiment_id": experiment_id, "created_at_utc": occurred_at},
        )
    event = {
        "event_type": "CAMPAIGN_APPROVED_AND_PREDECLARED",
        "campaign_id": campaign_id,
        "state": "APPROVED",
        "campaign_payload_hash": expected_payload_hash,
        "experiment_id": experiment_id,
        "approved_by": approved_by,
        "reason": reason,
    }
    event_id = f"{campaign_id}:APPROVED:{payload_hash(event)[:12]}"
    insert_immutable(
        connection,
        "campaign_events",
        "event_id",
        event_id,
        event,
        {
            "campaign_id": campaign_id,
            "state": "APPROVED",
            "occurred_at_utc": occurred_at,
            "actor": approved_by,
            "reason": reason,
        },
    )
    return {
        "campaign_id": campaign_id,
        "state": campaign_state(connection, campaign_id),
        "experiment_id": experiment_id,
        "approved_by": approved_by,
        "automatic_execution": False,
    }


def park_campaign(
    connection,
    campaign_id: str,
    *,
    expected_payload_hash: str,
    parked_by: str,
    reason: str,
    parked_at_utc: str | None = None,
) -> dict[str, Any]:
    """Append a human-reviewed terminal park event without rewriting evidence."""

    row = connection.execute(
        "SELECT payload_hash FROM research_campaigns WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()
    if row is None:
        raise ValueError("unknown campaign")
    if row["payload_hash"] != expected_payload_hash:
        raise ValueError("campaign payload hash does not match explicit park request")
    if not parked_by.strip() or parked_by.upper() in {"SYSTEM", "AGENT", "AUTOMATION"}:
        raise ValueError("parking requires a named human operator")
    if not reason.strip():
        raise ValueError("parking requires a reason")
    current = campaign_state(connection, campaign_id)
    if current != "APPROVED":
        raise ValueError(f"campaign parking requires APPROVED state, found {current}")
    occurred_at = parked_at_utc or utc_now()
    event = {
        "event_type": "CAMPAIGN_PARKED",
        "campaign_id": campaign_id,
        "state": "PARKED",
        "campaign_payload_hash": expected_payload_hash,
        "parked_by": parked_by,
        "reason": reason,
        "automatic_replacement": False,
    }
    event_id = f"{campaign_id}:PARKED:{payload_hash(event)[:12]}"
    insert_immutable(
        connection,
        "campaign_events",
        "event_id",
        event_id,
        event,
        {
            "campaign_id": campaign_id,
            "state": "PARKED",
            "occurred_at_utc": occurred_at,
            "actor": parked_by,
            "reason": reason,
        },
    )
    return {
        "campaign_id": campaign_id,
        "state": campaign_state(connection, campaign_id),
        "parked_by": parked_by,
        "reason": reason,
        "historical_specification_preserved": True,
        "automatic_replacement": False,
    }


def campaign_instruments(campaign: dict[str, Any]) -> list[str]:
    configured = campaign.get("instruments")
    return [str(value) for value in configured] if isinstance(configured, list) else [str(campaign["instrument"])]


DATA_CLASS_EQUIVALENTS = {
    "HISTORICAL_COMPLETED_CANDLES": {"COMPLETED_CANDLES"},
}


def _expanded_data_classes(values: set[str]) -> set[str]:
    expanded = set(values)
    for value in list(values):
        expanded.update(DATA_CLASS_EQUIVALENTS.get(value, set()))
    return expanded


def campaign_data_readiness(connection, campaign_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT payload_json FROM research_campaigns WHERE campaign_id=?", (campaign_id,)
    ).fetchone()
    if row is None:
        raise ValueError("unknown campaign")
    campaign = json.loads(row["payload_json"])
    required = {str(value) for value in campaign["required_data_classes"]}
    instruments = campaign_instruments(campaign)
    available_by_instrument: dict[str, set[str]] = {instrument: set() for instrument in instruments}
    windows: list[tuple[str, str]] = []
    for table in ("market_data_manifests", "evidence_manifests"):
        for manifest_row in connection.execute(
            f"SELECT payload_json FROM {table} WHERE usable_for_testing=1"
        ).fetchall():
            manifest = json.loads(manifest_row["payload_json"])
            instrument = str(manifest.get("instrument") or "")
            if instrument not in available_by_instrument:
                continue
            declared = {str(value) for value in manifest.get("data_classes", [])}
            available_by_instrument[instrument].update(_expanded_data_classes(declared))
            windows.append(
                (
                    str(manifest.get("window_start_utc") or ""),
                    str(manifest.get("window_end_utc") or ""),
                )
            )
    missing_by_instrument = {
        instrument: sorted(required - available)
        for instrument, available in available_by_instrument.items()
        if required - available
    }
    missing = sorted({value for values in missing_by_instrument.values() for value in values})
    missing_instruments = sorted(missing_by_instrument)
    available = set.intersection(*available_by_instrument.values()) if available_by_instrument else set()
    state = campaign_state(connection, campaign_id)
    return {
        "campaign_id": campaign_id,
        "campaign_state": state,
        "readiness_status": "READY" if not missing and state == "APPROVED" else "BLOCKED",
        "required_data_classes": sorted(required),
        "instruments": instruments,
        "available_data_classes": sorted(available),
        "available_data_classes_by_instrument": {
            instrument: sorted(values) for instrument, values in available_by_instrument.items()
        },
        "missing_data_classes": missing,
        "missing_data_classes_by_instrument": missing_by_instrument,
        "missing_instruments": missing_instruments,
        "usable_manifest_count": len(windows),
        "available_window_start_utc": min((value[0] for value in windows), default=None),
        "available_window_end_utc": max((value[1] for value in windows), default=None),
        "blocks": [
            *( ["campaign_not_human_approved"] if state == "DRAFT" else [] ),
            *( ["campaign_not_active"] if state not in {"DRAFT", "APPROVED"} else [] ),
            *( ["required_data_classes_missing"] if missing else [] ),
        ],
        "automatic_run_allowed": False,
    }


def campaign_report(connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT campaign_id, payload_hash, payload_json FROM research_campaigns ORDER BY created_at_utc, campaign_id"
    ).fetchall()
    campaigns = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        campaigns.append(
            {
                "campaign_id": row["campaign_id"],
                "title": payload["title"],
                "hypothesis_id": payload["hypothesis_id"],
                "state": campaign_state(connection, row["campaign_id"]),
                "payload_hash": row["payload_hash"],
                "readiness": campaign_data_readiness(connection, row["campaign_id"]),
            }
        )
    return {
        "campaign_count": len(campaigns),
        "campaigns": campaigns,
        "automatic_approval_allowed": False,
        "automatic_experiment_execution_allowed": False,
    }

