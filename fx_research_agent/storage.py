from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "FX_RESEARCH_AGENT_DB_V3"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def payload_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    initialize(connection)
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hypotheses (
            hypothesis_id TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source_repo TEXT NOT NULL,
            source_commit TEXT NOT NULL,
            source_path TEXT NOT NULL,
            imported_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hypothesis_events (
            event_id TEXT PRIMARY KEY,
            hypothesis_id TEXT NOT NULL,
            state TEXT NOT NULL,
            occurred_at_utc TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(hypothesis_id)
        );

        CREATE TABLE IF NOT EXISTS research_campaigns (
            campaign_id TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS campaign_events (
            event_id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            state TEXT NOT NULL,
            occurred_at_utc TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES research_campaigns(campaign_id)
        );

        CREATE INDEX IF NOT EXISTS idx_campaign_events_campaign_time
            ON campaign_events(campaign_id, occurred_at_utc, event_id);

        CREATE TABLE IF NOT EXISTS experiment_specs (
            experiment_id TEXT PRIMARY KEY,
            hypothesis_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            predeclared_at_utc TEXT NOT NULL,
            FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(hypothesis_id)
        );

        CREATE TABLE IF NOT EXISTS experiment_runs (
            run_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            started_at_utc TEXT NOT NULL,
            FOREIGN KEY (experiment_id) REFERENCES experiment_specs(experiment_id)
        );

        CREATE TABLE IF NOT EXISTS experiment_controls (
            control_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            FOREIGN KEY (experiment_id) REFERENCES experiment_specs(experiment_id)
        );

        CREATE TABLE IF NOT EXISTS findings (
            finding_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            knowable_at_utc TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES experiment_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS market_data_manifests (
            manifest_id TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            registered_at_utc TEXT NOT NULL,
            usable_for_testing INTEGER NOT NULL CHECK (usable_for_testing IN (0, 1))
        );

        CREATE TABLE IF NOT EXISTS evidence_manifests (
            manifest_id TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            registered_at_utc TEXT NOT NULL,
            usable_for_testing INTEGER NOT NULL CHECK (usable_for_testing IN (0, 1))
        );

        CREATE TABLE IF NOT EXISTS autonomy_policies (
            policy_id TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            registered_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_batches (
            batch_id TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS batch_campaigns (
            membership_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            added_at_utc TEXT NOT NULL,
            UNIQUE(batch_id, campaign_id),
            FOREIGN KEY (batch_id) REFERENCES research_batches(batch_id),
            FOREIGN KEY (campaign_id) REFERENCES research_campaigns(campaign_id)
        );

        CREATE TABLE IF NOT EXISTS campaign_progress_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES research_campaigns(campaign_id)
        );

        CREATE TABLE IF NOT EXISTS proposal_runs (
            proposal_run_id TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS proposal_candidates (
            proposal_id TEXT PRIMARY KEY,
            proposal_run_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            filter_status TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            FOREIGN KEY (proposal_run_id) REFERENCES proposal_runs(proposal_run_id)
        );

        CREATE TABLE IF NOT EXISTS downstream_exports (
            export_id TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            exported_at_utc TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SCHEMA_VERSION,),
    )
    connection.commit()


def insert_immutable(
    connection: sqlite3.Connection,
    table: str,
    id_column: str,
    record_id: str,
    payload: dict[str, Any],
    extra_columns: dict[str, Any],
) -> bool:
    digest = payload_hash(payload)
    existing = connection.execute(
        f"SELECT payload_hash FROM {table} WHERE {id_column} = ?", (record_id,)
    ).fetchone()
    if existing:
        if existing["payload_hash"] != digest:
            raise ValueError(f"conflicting immutable rewrite for {table}:{record_id}")
        return False

    columns = [id_column, "payload_hash", "payload_json", *extra_columns.keys()]
    values = [record_id, digest, canonical_json(payload), *extra_columns.values()]
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    connection.commit()
    return True

