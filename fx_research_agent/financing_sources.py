from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CATALOG_SCHEMA = "FX_G10_FINANCING_SOURCE_CATALOG_V1"
CONTRACT_SCHEMA = "FX_G10_LITERATURE_PANEL_CONTRACT_V1"
COMPLETE_PANEL_ROLE = "COMPLETE_CAMPAIGN_PANEL"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def load_catalog(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema") != CATALOG_SCHEMA:
        raise ValueError("unsupported G10 financing source catalog schema")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("financing source catalog must contain sources")
    source_ids = [source.get("source_id") for source in sources if isinstance(source, dict)]
    if len(source_ids) != len(sources) or any(not value for value in source_ids):
        raise ValueError("every financing source requires source_id")
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("duplicate financing source_id")
    return payload


def load_contract(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("unsupported G10 literature panel contract schema")
    return payload


def _complete_panel_blockers(source: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    required_instruments = set(contract["instruments"])
    source_instruments = set(source.get("instruments") or [])
    allowed_financing = set(contract["allowed_financing_source_types"])

    if source.get("campaign_role") != COMPLETE_PANEL_ROLE:
        blockers.append("not_complete_campaign_panel")
    if source.get("access_status") != "ACQUIRED_AND_CHECKSUMMED":
        blockers.append("not_acquired_and_checksummed")
    if source.get("raw_currency_level_rows") is not True:
        blockers.append("raw_currency_level_rows_not_verified")
    if source.get("financing_source_type") not in allowed_financing:
        blockers.append("observed_financing_or_forward_points_not_verified")
    if source.get("transaction_cost_source") != contract["transaction_cost_source"]:
        blockers.append("historical_bid_ask_costs_not_verified")
    if not required_instruments.issubset(source_instruments):
        blockers.append("nine_instrument_coverage_not_verified")
    if int(source.get("common_month_count") or 0) < int(contract["minimum_common_months"]):
        blockers.append("minimum_common_months_not_met")
    if not source.get("artifact_sha256"):
        blockers.append("artifact_checksum_missing")
    if source.get("immutable_lineage") is not True:
        blockers.append("immutable_lineage_not_verified")
    return blockers


def audit_catalog(catalog: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise ValueError("unsupported G10 financing source catalog schema")
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("unsupported G10 literature panel contract schema")

    source_rows = []
    ready_sources = []
    financing_candidates = []
    benchmark_sources = []
    for source in catalog["sources"]:
        blockers = _complete_panel_blockers(source, contract)
        row = {
            "source_id": source["source_id"],
            "campaign_role": source.get("campaign_role"),
            "access_status": source.get("access_status"),
            "complete_panel_ready": not blockers,
            "complete_panel_blockers": blockers,
        }
        source_rows.append(row)
        if not blockers:
            ready_sources.append(source["source_id"])
        if source.get("campaign_role") == "FINANCING_INPUT_CANDIDATE":
            financing_candidates.append(source["source_id"])
        if source.get("campaign_role") == "BENCHMARK_ONLY":
            benchmark_sources.append(source["source_id"])

    ready = bool(ready_sources)
    return {
        "schema": "FX_G10_FINANCING_SOURCE_AUDIT_V1",
        "campaign_id": "CAMPAIGN_G10_CROSS_SECTIONAL_MOMENTUM_V1",
        "status": "READY" if ready else "BLOCKED_SOURCE_ACQUISITION",
        "campaign_4_data_ready": ready,
        "campaign_5_carry_predeclaration_allowed": ready,
        "minimum_common_months": int(contract["minimum_common_months"]),
        "required_instruments": list(contract["instruments"]),
        "ready_complete_panel_sources": ready_sources,
        "financing_input_candidates": financing_candidates,
        "benchmark_only_sources": benchmark_sources,
        "sources": source_rows,
        "next_action": (
            "Register and checksum the qualifying complete panel."
            if ready
            else "Acquire raw currency-level one-month forward or historical financing data for all nine instruments, combine it with historical bid/ask costs, checksum the assembled panel, and rerun this audit."
        ),
    }


def audit_paths(catalog_path: Path, contract_path: Path) -> dict[str, Any]:
    return audit_catalog(load_catalog(catalog_path), load_contract(contract_path))
