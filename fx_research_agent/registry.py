from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import insert_immutable, payload_hash


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "EUR_AGENT_RESEARCH_HYPOTHESIS_REGISTRY_V1":
        raise ValueError("unsupported genesis registry schema")
    hypotheses = payload.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise ValueError("genesis registry must contain hypotheses")
    return payload


def import_genesis(
    connection,
    registry_path: Path,
    source_repo: str,
    source_commit: str,
    source_path: str,
    imported_at_utc: str | None = None,
) -> dict[str, int]:
    registry = load_registry(registry_path)
    imported_at = imported_at_utc or utc_now()
    counts = {"inserted": 0, "unchanged": 0}
    for hypothesis in registry["hypotheses"]:
        hypothesis_id = hypothesis["hypothesis_id"]
        inserted = insert_immutable(
            connection,
            "hypotheses",
            "hypothesis_id",
            hypothesis_id,
            hypothesis,
            {
                "source_repo": source_repo,
                "source_commit": source_commit,
                "source_path": source_path,
                "imported_at_utc": imported_at,
            },
        )
        counts["inserted" if inserted else "unchanged"] += 1
        event_payload = {
            "event_type": "GENESIS_IMPORT",
            "hypothesis_id": hypothesis_id,
            "state": hypothesis["state"],
            "source_payload_hash": payload_hash(hypothesis),
            "source_repo": source_repo,
            "source_commit": source_commit,
            "source_path": source_path,
        }
        event_id = f"GENESIS_{hypothesis_id}"
        insert_immutable(
            connection,
            "hypothesis_events",
            "event_id",
            event_id,
            event_payload,
            {
                "hypothesis_id": hypothesis_id,
                "state": hypothesis["state"],
                "occurred_at_utc": hypothesis["proposed_at_utc"],
                "actor": "GENESIS_IMPORTER",
                "reason": "PRESERVE_EXISTING_EUR_AGENT_RESEARCH_HISTORY",
            },
        )
    return counts


def backlog(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT hypothesis_id, payload_json
        FROM hypotheses
        ORDER BY json_extract(payload_json, '$.priority'), hypothesis_id
        """
    ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def hypothesis_state(connection, hypothesis_id: str) -> str | None:
    row = connection.execute(
        "SELECT state FROM hypothesis_events WHERE hypothesis_id=? "
        "ORDER BY occurred_at_utc DESC, event_id DESC LIMIT 1",
        (hypothesis_id,),
    ).fetchone()
    return str(row["state"]) if row else None


def review_hypothesis(
    connection,
    hypothesis_id: str,
    *,
    decision: str,
    reviewed_by: str,
    reason: str,
    reviewed_at_utc: str | None = None,
) -> dict[str, Any]:
    if connection.execute(
        "SELECT 1 FROM hypotheses WHERE hypothesis_id=?", (hypothesis_id,)
    ).fetchone() is None:
        raise ValueError("unknown hypothesis")
    if hypothesis_state(connection, hypothesis_id) != "PROPOSED":
        raise ValueError("human review requires a PROPOSED hypothesis")
    if not reviewed_by.strip() or reviewed_by.upper() in {"SYSTEM", "AGENT", "AUTOMATION"}:
        raise ValueError("hypothesis review requires a named human")
    if not reason.strip():
        raise ValueError("hypothesis review requires a reason")
    state_by_decision = {
        "APPROVE_FOR_CAMPAIGN_DRAFT": "REVIEWED_FOR_CAMPAIGN_DRAFT",
        "REJECT": "REJECTED",
        "SUPERSEDE": "SUPERSEDED",
    }
    if decision not in state_by_decision:
        raise ValueError("unsupported hypothesis review decision")
    occurred_at = reviewed_at_utc or utc_now()
    state = state_by_decision[decision]
    event = {
        "event_type": "HUMAN_HYPOTHESIS_REVIEW",
        "hypothesis_id": hypothesis_id,
        "decision": decision,
        "state": state,
        "reviewed_by": reviewed_by,
        "reason": reason,
    }
    event_id = f"{hypothesis_id}:{state}:{payload_hash(event)[:12]}"
    insert_immutable(
        connection,
        "hypothesis_events",
        "event_id",
        event_id,
        event,
        {
            "hypothesis_id": hypothesis_id,
            "state": state,
            "occurred_at_utc": occurred_at,
            "actor": reviewed_by,
            "reason": reason,
        },
    )
    return {
        "hypothesis_id": hypothesis_id,
        "state": state,
        "campaign_created": False,
        "campaign_approved": False,
        "order_authority": False,
    }


def status(connection) -> dict[str, Any]:
    state_rows = connection.execute(
        """
        SELECT json_extract(payload_json, '$.state') AS state, COUNT(*) AS count
        FROM hypotheses
        GROUP BY state
        ORDER BY state
        """
    ).fetchall()
    return {
        "schema_version": connection.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()["value"],
        "hypothesis_count": connection.execute("SELECT COUNT(*) AS n FROM hypotheses").fetchone()["n"],
        "state_counts": {row["state"]: row["count"] for row in state_rows},
        "campaign_count": connection.execute("SELECT COUNT(*) AS n FROM research_campaigns").fetchone()["n"],
        "experiment_count": connection.execute("SELECT COUNT(*) AS n FROM experiment_specs").fetchone()["n"],
        "finding_count": connection.execute("SELECT COUNT(*) AS n FROM findings").fetchone()["n"],
        "market_manifest_count": connection.execute("SELECT COUNT(*) AS n FROM market_data_manifests").fetchone()["n"],
        "downstream_export_count": connection.execute("SELECT COUNT(*) AS n FROM downstream_exports").fetchone()["n"],
    }

