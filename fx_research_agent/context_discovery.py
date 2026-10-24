from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .market_data import validate_manifest
from .storage import canonical_json, insert_immutable


CONTRACT_SCHEMA = "FX_CONTEXT_DISCOVERY_CONTRACT_V1"
AUDIT_SCHEMA = "FX_CONTEXT_COVERAGE_AUDIT_V1"
FORBIDDEN_FEATURE_TOKENS = (
    "outcome", "forward", "target", "terminal", "mfe", "mae", "pnl", "net_r",
    "strategy", "family", "candidate", "signal", "label",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_payload(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("unsupported context discovery contract")
    sources = payload.get("required_sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("context discovery requires at least one source")
    identities = [(str(row.get("instrument")), str(row.get("granularity"))) for row in sources]
    if len(identities) != len(set(identities)):
        raise ValueError("context discovery source identities must be unique")
    features = payload.get("feature_names")
    if not isinstance(features, list) or not features or len(features) != len(set(features)):
        raise ValueError("context discovery feature names must be unique and non-empty")
    offending = [name for name in features if any(token in str(name).lower() for token in FORBIDDEN_FEATURE_TOKENS)]
    if offending:
        raise ValueError(f"future/strategy-derived context features are forbidden: {offending}")
    if payload.get("future_outcomes_allowed_in_features") is not False:
        raise ValueError("context discovery must exclude future outcomes")
    authority = payload.get("authority") if isinstance(payload.get("authority"), dict) else {}
    if authority.get("research_only") is not True or authority.get("paper_or_live_authority") is not False:
        raise ValueError("context discovery must remain research-only")
    return payload


def _registered_manifests(connection, instrument: str, data_class: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    rows = connection.execute(
        "SELECT payload_json, usable_for_testing FROM market_data_manifests ORDER BY registered_at_utc"
    ).fetchall()
    for row in rows:
        manifest = json.loads(row["payload_json"])
        if not int(row["usable_for_testing"]):
            continue
        if manifest.get("instrument") != instrument:
            continue
        if data_class not in set(manifest.get("data_classes") or []):
            continue
        output.append(manifest)
    return output


def audit_context_coverage(
    connection,
    *,
    contract_path: Path,
    inbox_dir: Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    created = created_at_utc or utc_now()
    development = contract["development"]
    start = str(development["start_utc"])
    end = str(development["end_utc_exclusive"])
    source_results: list[dict[str, Any]] = []

    for source in contract["required_sources"]:
        instrument = str(source["instrument"])
        granularity = str(source["granularity"])
        data_class = str(source.get("source_data_class") or "HISTORICAL_COMPLETED_CANDLES")
        manifests = _registered_manifests(connection, instrument, data_class)
        candles: dict[str, dict[str, Any]] = {}
        source_lineage: list[dict[str, Any]] = []
        for manifest in manifests:
            manifest_path = inbox_dir / f"{manifest['manifest_id']}.manifest.json"
            if not manifest_path.is_file():
                raise ValueError(f"registered context manifest missing from inbox: {manifest['manifest_id']}")
            validated = validate_manifest(manifest_path)
            payload_path = inbox_dir / str(validated["payload_path"])
            payload = _load_payload(payload_path)
            if payload.get("schema") != "FX_HISTORICAL_MARKET_DATA_PAYLOAD_V1":
                raise ValueError("context discovery requires sealed historical candle payloads")
            quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
            if quality.get("future_outcomes_exported") is not False or quality.get("strategy_labels_exported") is not False:
                raise ValueError("context source does not prove outcome/label exclusion")
            for candle in payload.get("completed_candles") or []:
                if candle.get("instrument") != instrument or candle.get("granularity") != granularity:
                    continue
                time_utc = str(candle.get("candle_time_utc") or "")
                if not start <= time_utc < end:
                    continue
                existing = candles.get(time_utc)
                if existing is not None and canonical_json(existing) != canonical_json(candle):
                    raise ValueError(f"conflicting historical context candle rewrite: {(instrument, granularity, time_utc)}")
                candles[time_utc] = candle
            source_lineage.append(
                {
                    "manifest_id": manifest["manifest_id"],
                    "payload_sha256": manifest["payload_sha256"],
                    "window_start_utc": manifest["window_start_utc"],
                    "window_end_utc": manifest["window_end_utc"],
                }
            )
        ordered_times = sorted(candles)
        distinct_days = len({value[:10] for value in ordered_times})
        minimum_rows = int(source["minimum_development_rows"])
        minimum_days = int(source.get("minimum_distinct_days") or 0)
        blocks: list[str] = []
        if len(ordered_times) < minimum_rows:
            blocks.append("development_row_count_below_minimum")
        if distinct_days < minimum_days:
            blocks.append("development_distinct_days_below_minimum")
        if not source_lineage:
            blocks.append("sealed_source_manifest_missing")
        source_results.append(
            {
                "source_id": source["source_id"],
                "role": source["role"],
                "instrument": instrument,
                "granularity": granularity,
                "development_row_count": len(ordered_times),
                "development_distinct_day_count": distinct_days,
                "first_development_candle_utc": ordered_times[0] if ordered_times else None,
                "last_development_candle_utc": ordered_times[-1] if ordered_times else None,
                "minimum_development_rows": minimum_rows,
                "minimum_distinct_days": minimum_days,
                "status": "PASS" if not blocks else "BLOCKED",
                "blocks": blocks,
                "source_lineage": source_lineage,
            }
        )

    blocked = [row["source_id"] for row in source_results if row["status"] != "PASS"]
    identity = {
        "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "sources": [
            {
                "source_id": row["source_id"],
                "lineage": row["source_lineage"],
                "rows": row["development_row_count"],
            }
            for row in source_results
        ],
    }
    audit_id = "FX_CONTEXT_COVERAGE_" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:20]
    existing = connection.execute(
        "SELECT payload_json FROM context_coverage_audits WHERE audit_id=?",
        (audit_id,),
    ).fetchone()
    if existing is not None:
        return json.loads(existing["payload_json"])
    report = {
        "schema": AUDIT_SCHEMA,
        "audit_id": audit_id,
        "created_at_utc": created,
        "contract_id": contract["contract_id"],
        "contract_sha256": identity["contract_sha256"],
        "coverage_status": "READY_FOR_OUTCOME_BLIND_CONTEXT_DISCOVERY" if not blocked else "BLOCKED_DATA_COVERAGE",
        "development": development,
        "source_results": source_results,
        "blocked_source_ids": blocked,
        "excluded_sources": contract.get("excluded_sources") or [],
        "safety": {
            "future_outcomes_read": False,
            "strategy_labels_read": False,
            "validation_or_holdout_outcomes_read": False,
            "campaign_created": False,
            "downstream_export_created": False,
            "paper_or_live_authority": False,
        },
    }
    insert_immutable(
        connection,
        "context_coverage_audits",
        "audit_id",
        audit_id,
        report,
        {"created_at_utc": created},
    )
    return report
