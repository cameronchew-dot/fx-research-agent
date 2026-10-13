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

