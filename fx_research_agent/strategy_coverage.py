from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_payload(
    connection,
    table: str,
    where_column: str,
    value: str,
    order_clause: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        f"SELECT payload_json FROM {table} WHERE {where_column}=? "
        f"ORDER BY {order_clause} LIMIT 1",
        (value,),
    ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def build_strategy_coverage(
    connection,
    *,
    eur_bot_root: Path,
    contract_path: Path,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    contract = _read_json(contract_path)
    registry = _read_json(eur_bot_root / "config" / "eur_family_plugins.json")
    validation = _read_json(eur_bot_root / "data" / "eur_family_validation.json")
    lifecycle = _read_json(eur_bot_root / "data" / "eur_lifecycle_registry.json")
    portfolio = _read_json(eur_bot_root / "data" / "eur_portfolio_integrity.json")
    execution = _read_json(eur_bot_root / "config" / "eur_oanda_practice_execution_contract.json")

    families = {str(row["id"]): row for row in registry.get("families", [])}
    evaluations = {
        str(row["family_id"]): row for row in validation.get("evaluations", [])
    }
    active_profiles = lifecycle.get("active_profile_candidate_auto_queue", [])
    profiles_by_family: dict[str, list[dict[str, Any]]] = {}
    for profile in active_profiles:
        profiles_by_family.setdefault(str(profile.get("family_id")), []).append(profile)

    campaigns: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        "SELECT campaign_id, payload_json FROM research_campaigns ORDER BY campaign_id"
    ).fetchall():
        campaign_id = str(row["campaign_id"])
        payload = json.loads(row["payload_json"])
        state_row = connection.execute(
            "SELECT state FROM campaign_events WHERE campaign_id=? "
            "ORDER BY occurred_at_utc DESC, event_id DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()
        latest_run = _latest_payload(
            connection, "experiment_runs", "experiment_id", f"EXP_{campaign_id}",
            "started_at_utc DESC, run_id DESC",
        )
        latest_review = _latest_payload(
            connection, "campaign_reviews", "campaign_id", campaign_id,
            "reviewed_at_utc DESC, review_id DESC",
        )
        campaigns[campaign_id] = {
            "campaign_id": campaign_id,
            "title": payload.get("title"),
            "state": state_row["state"] if state_row else payload.get("state"),
            "mechanism_class": payload.get("mechanism_class"),
            "latest_review_status": latest_run.get("review_status") if latest_run else None,
            "independent_episode_count": latest_run.get("independent_episode_count") if latest_run else 0,
            "latest_human_decision": latest_review.get("decision") if latest_review else None,
            "confirmatory_cutover_at_utc": latest_review.get("confirmatory_cutover_at_utc") if latest_review else None,
            "automatic_promotion_allowed": False,
            "downstream_authority": "NONE",
        }

    covered_families: set[str] = set()
    covered_campaigns: set[str] = set()
    groups = []
    for specification in contract.get("groups", []):
        family_rows = []
        missing_family_ids = []
        for family_id in specification.get("family_ids", []):
            family = families.get(family_id)
            if family is None:
                missing_family_ids.append(family_id)
                continue
            covered_families.add(family_id)
            evaluation = evaluations.get(family_id)
            family_rows.append(
                {
                    "family_id": family_id,
                    "display_name": family.get("display_name"),
                    "generator_status": (family.get("generator") or {}).get("status"),
                    "registry_stage": (family.get("lifecycle") or {}).get("stage"),
                    "validation_decision": evaluation.get("validation_decision") if evaluation else None,
                    "candidate_count": (evaluation.get("metrics") or {}).get("count") if evaluation else None,
                    "avg_net_r_close": (evaluation.get("metrics") or {}).get("avg_net_r_close") if evaluation else None,
                    "positive_close_rate": (evaluation.get("metrics") or {}).get("positive_close_rate") if evaluation else None,
                    "active_profile_count": len(profiles_by_family.get(family_id, [])),
                    "active_profile_ids": [row.get("profile_id") for row in profiles_by_family.get(family_id, [])],
                }
            )
        campaign_rows = []
        missing_campaign_ids = []
        for campaign_id in specification.get("campaign_ids", []):
            campaign = campaigns.get(campaign_id)
            if campaign is None:
                missing_campaign_ids.append(campaign_id)
                continue
            covered_campaigns.add(campaign_id)
            campaign_rows.append(campaign)
        groups.append(
            {
                "group_id": specification["group_id"],
                "families": family_rows,
                "campaigns": campaign_rows,
                "missing_family_ids": missing_family_ids,
                "missing_campaign_ids": missing_campaign_ids,
            }
        )

    validation_summary = validation.get("summary") or {}
    exact_cadence = portfolio.get("exact_historical_profile_cadence") or {}
    selector_metrics = exact_cadence.get("selector_realistic_metrics") or {}
    return {
        "schema": "FX_STRATEGY_COVERAGE_REPORT_V1",
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_schema": contract.get("schema"),
        "summary": {
            "registered_family_count": len(families),
            "validated_family_count": len(evaluations),
            "broad_validation_pass_count": validation_summary.get(
                "paper_candidate_metric_pass_count", 0
            ),
            "active_profile_count": len(active_profiles),
            "research_campaign_count": len(campaigns),
            "covered_family_count": len(covered_families),
            "covered_campaign_count": len(covered_campaigns),
            "portfolio_status": portfolio.get("portfolio_integrity_status"),
            "exact_historical_avg_trades_per_week": selector_metrics.get(
                "avg_events_per_week"
            ),
        },
        "mechanism_groups": groups,
        "unmapped_family_ids": sorted(set(families) - covered_families),
        "unmapped_campaign_ids": sorted(set(campaigns) - covered_campaigns),
        "execution_snapshot": {
            "venue": execution.get("venue"),
            "reference_equity_usd": (execution.get("reference_account_model") or {}).get("reference_equity_usd"),
            "risk_per_trade_fraction": (execution.get("reference_account_model") or {}).get("risk_per_trade_fraction"),
            "broker_account_balance_used_for_sizing": (execution.get("reference_account_model") or {}).get("broker_account_balance_used_for_sizing"),
            "max_open_managed_trades": (execution.get("reference_account_model") or {}).get("max_open_managed_trades"),
        },
        "safety": {
            "reporting_only": True,
            "lifecycle_written": False,
            "selector_written": False,
            "risk_sizing_changed": False,
            "orders_submitted": False,
            "live_enabled": False,
        },
    }
