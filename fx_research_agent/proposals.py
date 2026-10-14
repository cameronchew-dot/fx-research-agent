from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .automation import current_policy
from .batches import active_slot_count
from .registry import hypothesis_state
from .storage import insert_immutable, payload_hash


ANTHROPIC_VERSION = "2023-06-01"
PROPOSAL_SCHEMA = "FX_RESEARCH_PROPOSAL_V1"
Provider = Callable[[dict[str, Any], dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _proposal_json_schema(maximum: int) -> dict[str, Any]:
    proposal = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "statement": {"type": "string"},
            "mechanism_class": {"type": "string"},
            "instrument": {"type": "string", "enum": ["EUR_USD"]},
            "hypothesis_type": {"type": "string"},
            "classification": {"type": "string"},
            "causal_rationale": {"type": "string"},
            "data_requirements": {"type": "array", "items": {"type": "string"}},
            "expected_frequency": {"type": "string"},
            "population": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "inclusion_rule": {"type": "string"},
                    "exclusion_rule": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "decision_time_rule": {"type": "string"},
                },
                "required": ["inclusion_rule", "exclusion_rule", "timeframe", "decision_time_rule"],
            },
            "exact_specification": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "field": {"type": "string"},
                        "operator": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["field", "operator", "value"],
                },
            },
            "controls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "control_id": {"type": "string"},
                        "definition": {"type": "string"},
                        "post_selection_mutation_allowed": {"type": "boolean"},
                    },
                    "required": ["control_id", "definition", "post_selection_mutation_allowed"],
                },
            },
            "primary_metric": {"type": "string"},
            "independence_unit": {"type": "string"},
            "overlap_notes": {"type": "string"},
            "falsification_condition": {"type": "string"},
            "estimated_sample_gate": {"type": "integer"},
        },
        "required": [
            "title", "statement", "mechanism_class", "instrument",
            "hypothesis_type", "classification", "causal_rationale",
            "data_requirements", "expected_frequency", "population",
            "exact_specification", "controls", "primary_metric",
            "independence_unit", "overlap_notes", "falsification_condition",
            "estimated_sample_gate",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "proposals": {
                "type": "array",
                "items": proposal,
            }
        },
        "required": ["proposals"],
    }


def _anthropic_provider(policy: dict[str, Any], input_packet: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("FX_RESEARCH_ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ValueError("FX_RESEARCH_ANTHROPIC_API_KEY is missing")
    maximum = int(input_packet["maximum_proposals_this_cycle"])
    body = {
        "model": policy["model"],
        "max_tokens": int(policy["maximum_output_tokens"]),
        "system": (
            "You are a governed FX research hypothesis proposer. Propose only falsifiable, "
            "causally motivated, cost-aware EUR/USD hypotheses using the supplied data. "
            f"Lock one exact specification per proposal and emit no more than {maximum}. "
            "Do not tune from findings, claim edge, "
            "create campaigns, approve work, or recommend orders. Return one to three COMPLETE "
            "proposals only when every required field can be populated. Each proposal must have "
            "at least one exact field/operator/value clause, at least one immutable control with "
            "post_selection_mutation_allowed=false, and a sample gate of at least 10. Never emit "
            "blank strings, empty specifications, empty controls, or placeholder values. If no "
            "honest complete proposal is possible, return an empty proposals array. Return only "
            "the required schema."
        ),
        "messages": [{
            "role": "user",
            "content": (
                "Generate the bounded weekly hypothesis proposals now. Use only the supplied "
                "blind registry and data-capability packet. Prefer a mechanism and signal "
                "population that is distinct from occupied campaigns. Every emitted proposal "
                "must be complete and immediately suitable for human review; otherwise emit "
                "no proposal.\n\nINPUT_PACKET=" + json.dumps(input_packet, sort_keys=True)
            ),
        }],
        "output_config": {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _proposal_json_schema(maximum)},
        },
    }
    request = Request(
        policy["endpoint"],
        data=json.dumps(body, sort_keys=True).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "user-agent": "fx-research-agent/1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            raw = json.loads(response.read().decode("utf-8"))
            request_id = response.headers.get("request-id")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ValueError(f"Anthropic HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Anthropic proposal call failed: {exc}") from exc
    if str(raw.get("model") or "") != policy["model"]:
        raise ValueError("Anthropic response model did not match the pinned model")
    blocks = [item.get("text") for item in raw.get("content", []) if item.get("type") == "text"]
    if len(blocks) != 1:
        raise ValueError("Anthropic response did not contain one structured proposal object")
    try:
        output = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise ValueError("Anthropic proposal output was not valid JSON") from exc
    usage = raw.get("usage") or {}
    return output, {
        "provider_request_id": request_id or raw.get("id"),
        "response_model": raw.get("model"),
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
    }


def _available_data_classes(connection) -> list[str]:
    values: set[str] = set()
    for table in ("market_data_manifests", "evidence_manifests"):
        rows = connection.execute(
            f"SELECT payload_json FROM {table} WHERE usable_for_testing=1"
        ).fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            values.update(str(value) for value in payload.get("data_classes", []))
    return sorted(values)


def build_blind_input(connection) -> dict[str, Any]:
    hypotheses = []
    for row in connection.execute(
        "SELECT hypothesis_id, payload_json FROM hypotheses ORDER BY hypothesis_id"
    ).fetchall():
        payload = json.loads(row["payload_json"])
        hypotheses.append({
            key: payload.get(key)
            for key in (
                "hypothesis_id", "state", "hypothesis_type", "classification",
                "statement", "data_requirements", "expected_frequency", "overlap_notes",
            )
        })
    campaigns = []
    for row in connection.execute(
        "SELECT campaign_id, payload_json FROM research_campaigns ORDER BY campaign_id"
    ).fetchall():
        payload = json.loads(row["payload_json"])
        campaigns.append({
            key: payload.get(key)
            for key in (
                "campaign_id", "hypothesis_id", "instrument", "mechanism_class",
                "research_question", "population", "independence_unit",
                "exact_specification", "controls", "review_gates",
                "multiple_comparisons_policy", "stopping_rules",
            )
        })
    return {
        "schema": "FX_RESEARCH_PROPOSER_INPUT_V1",
        "objective": "Find independent, falsifiable EUR/USD research questions; do not infer success.",
        "available_data_classes": _available_data_classes(connection),
        "existing_hypotheses": hypotheses,
        "campaign_specifications_without_results": campaigns,
        "occupied_campaign_slots": active_slot_count(connection),
        "campaign_slot_limit": 3,
        "constraints": {
            "one_exact_specification": True,
            "parameter_sweeps_allowed": False,
            "controls_required": True,
            "human_campaign_approval_required": True,
            "evidence_results_blind": True,
            "order_authority": False,
        },
    }


def _pending_machine_proposal_count(connection) -> int:
    rows = connection.execute(
        "SELECT hypothesis_id FROM hypotheses WHERE source_repo='LOCAL_AUTONOMOUS_PROPOSER'"
    ).fetchall()
    return sum(hypothesis_state(connection, row["hypothesis_id"]) == "PROPOSED" for row in rows)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


def _jaccard(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a | b else 1.0


def _contains_forbidden_result_key(value: Any) -> bool:
    forbidden = {
        "finding_id",
        "realized_net_r",
        "average_net_r",
        "median_net_r",
        "positive_net_r_rate",
        "minimum_net_r",
        "maximum_net_r",
    }
    if isinstance(value, dict):
        return any(str(key).lower() in forbidden or _contains_forbidden_result_key(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_result_key(child) for child in value)
    return False


def _validate_candidate(
    proposal: Any,
    *,
    available_data: set[str],
    existing_statements: list[str],
    duplicate_threshold: float,
) -> tuple[str, list[str]]:
    errors: list[str] = []
    required = set(_proposal_json_schema(3)["properties"]["proposals"]["items"]["required"])
    if not isinstance(proposal, dict):
        return "REJECTED_SCHEMA", ["PROPOSAL_NOT_OBJECT"]
    missing = sorted(required - set(proposal))
    if missing:
        errors.append("MISSING_FIELDS:" + ",".join(missing))
    if proposal.get("instrument") != "EUR_USD":
        errors.append("UNSUPPORTED_INSTRUMENT")
    if not isinstance(proposal.get("exact_specification"), (dict, list)) or not proposal.get("exact_specification"):
        errors.append("EXACT_SPECIFICATION_REQUIRED")
    if not isinstance(proposal.get("controls"), list) or not proposal.get("controls"):
        errors.append("CONTROL_REQUIRED")
    elif any(control.get("post_selection_mutation_allowed") is not False for control in proposal["controls"]):
        errors.append("CONTROL_MUTATION_MUST_BE_DISABLED")
    if not isinstance(proposal.get("estimated_sample_gate"), int) or int(proposal["estimated_sample_gate"]) < 10:
        errors.append("SAMPLE_GATE_MUST_BE_AT_LEAST_10")
    if errors:
        return "REJECTED_SCHEMA", errors
    statement = str(proposal["statement"])
    if any(_jaccard(statement, prior) >= duplicate_threshold for prior in existing_statements):
        return "REJECTED_DUPLICATE", ["STATEMENT_TOO_SIMILAR_TO_EXISTING_HYPOTHESIS"]
    required_data = {str(value) for value in proposal["data_requirements"]}
    missing_data = sorted(required_data - available_data)
    if missing_data:
        return "BLOCKED_DATA", ["MISSING_DATA:" + ",".join(missing_data)]
    return "ACCEPTED_PROPOSED", []


def run_proposal_cycle(
    connection,
    *,
    provider: Provider | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    policy = current_policy(connection)
    if policy.get("provider") != "ANTHROPIC":
        raise ValueError("only the governed Anthropic proposal provider is supported")
    if policy.get("authority", {}).get("automatic_hypothesis_proposal") is not True:
        raise ValueError("automatic hypothesis proposals are disabled")
    pending = _pending_machine_proposal_count(connection)
    pending_cap = int(policy["maximum_pending_machine_proposals"])
    if pending >= pending_cap:
        return {
            "proposal_cycle_status": "SKIPPED_PENDING_REVIEW_CAP",
            "pending_machine_proposal_count": pending,
            "maximum_pending_machine_proposals": pending_cap,
            "provider_call_made": False,
            "campaigns_created": 0,
            "campaigns_approved": 0,
            "order_authority": False,
        }
    maximum_this_cycle = min(int(policy["maximum_proposals_per_cycle"]), pending_cap - pending)
    created_at = created_at_utc or utc_now()
    input_packet = build_blind_input(connection)
    input_packet["maximum_proposals_this_cycle"] = maximum_this_cycle
    if _contains_forbidden_result_key(input_packet):
        raise ValueError("proposal input blindness invariant failed")
    output, provider_meta = (provider or _anthropic_provider)(policy, input_packet)
    proposals = output.get("proposals") if isinstance(output, dict) else None
    maximum = maximum_this_cycle
    if not isinstance(proposals, list) or len(proposals) > maximum:
        raise ValueError("proposal provider exceeded the locked proposal count")
    identity = {
        "policy_id": policy["policy_id"],
        "model": policy["model"],
        "prompt_version": policy["prompt_version"],
        "input_hash": payload_hash(input_packet),
        "output_hash": payload_hash(output),
        "created_at_utc": created_at,
    }
    run_id = "PROPOSAL_RUN_" + payload_hash(identity)[:24]
    run_payload = {
        "schema": "FX_RESEARCH_PROPOSAL_RUN_V1",
        "proposal_run_id": run_id,
        "created_at_utc": created_at,
        **identity,
        "provider": policy["provider"],
        "provider_request_id": provider_meta.get("provider_request_id"),
        "input_tokens": int(provider_meta.get("input_tokens") or 0),
        "output_tokens": int(provider_meta.get("output_tokens") or 0),
        "proposal_count": len(proposals),
        "blind_input_invariants": {
            "findings_excluded": True,
            "net_r_excluded": True,
            "hidden_holdouts_excluded": True,
        },
        "automatic_campaign_creation": False,
        "automatic_approval": False,
        "order_authority": False,
    }
    insert_immutable(
        connection, "proposal_runs", "proposal_run_id", run_id, run_payload,
        {"created_at_utc": created_at},
    )
    existing = [
        str(json.loads(row["payload_json"]).get("statement") or "")
        for row in connection.execute("SELECT payload_json FROM hypotheses").fetchall()
    ]
    available = set(input_packet["available_data_classes"])
    results = []
    for index, proposal in enumerate(proposals, start=1):
        status, reasons = _validate_candidate(
            proposal,
            available_data=available,
            existing_statements=existing,
            duplicate_threshold=float(policy["duplicate_statement_jaccard_threshold"]),
        )
        proposal_id = f"{run_id}:P{index}"
        record = {
            "schema": PROPOSAL_SCHEMA,
            "proposal_id": proposal_id,
            "proposal_run_id": run_id,
            "created_at_utc": created_at,
            "filter_status": status,
            "filter_reasons": reasons,
            "proposal": proposal,
        }
        insert_immutable(
            connection, "proposal_candidates", "proposal_id", proposal_id, record,
            {"proposal_run_id": run_id, "filter_status": status, "created_at_utc": created_at},
        )
        hypothesis_id = None
        if status == "ACCEPTED_PROPOSED":
            hypothesis_id = "HYP_AUTO_" + payload_hash(proposal)[:20].upper()
            hypothesis = {
                "hypothesis_id": hypothesis_id,
                "proposed_at_utc": created_at,
                "proposed_by": "ANTHROPIC_GOVERNED_PROPOSER",
                "state": "PROPOSED",
                "hypothesis_type": proposal["hypothesis_type"],
                "classification": proposal["classification"],
                "priority": 100 + index,
                "statement": proposal["statement"],
                "mechanism_class": proposal["mechanism_class"],
                "instrument": proposal["instrument"],
                "causal_rationale": proposal["causal_rationale"],
                "data_requirements": proposal["data_requirements"],
                "expected_frequency": proposal["expected_frequency"],
                "population": proposal["population"],
                "exact_specification": proposal["exact_specification"],
                "controls": proposal["controls"],
                "primary_metric": proposal["primary_metric"],
                "independence_unit": proposal["independence_unit"],
                "estimated_sample_gate": proposal["estimated_sample_gate"],
                "overlap_notes": proposal["overlap_notes"],
                "falsification_condition": proposal["falsification_condition"],
                "proposal_run_id": run_id,
                "next_action": "HUMAN_REVIEW_REQUIRED_BEFORE_CAMPAIGN_DRAFT",
            }
            insert_immutable(
                connection, "hypotheses", "hypothesis_id", hypothesis_id, hypothesis,
                {
                    "source_repo": "LOCAL_AUTONOMOUS_PROPOSER",
                    "source_commit": policy["model"],
                    "source_path": run_id,
                    "imported_at_utc": created_at,
                },
            )
            event = {
                "event_type": "AUTONOMOUS_PROPOSAL_ACCEPTED",
                "hypothesis_id": hypothesis_id,
                "state": "PROPOSED",
                "proposal_id": proposal_id,
                "proposal_run_id": run_id,
            }
            insert_immutable(
                connection, "hypothesis_events", "event_id", f"{hypothesis_id}:PROPOSED",
                event,
                {
                    "hypothesis_id": hypothesis_id,
                    "state": "PROPOSED",
                    "occurred_at_utc": created_at,
                    "actor": "GOVERNED_PROPOSER",
                    "reason": "PASSED_DETERMINISTIC_PROPOSAL_FILTERS_HUMAN_REVIEW_REQUIRED",
                },
            )
            existing.append(str(proposal["statement"]))
        results.append({"proposal_id": proposal_id, "status": status, "reasons": reasons, "hypothesis_id": hypothesis_id})
    return {
        "proposal_run_id": run_id,
        "provider": policy["provider"],
        "model": policy["model"],
        "input_tokens": run_payload["input_tokens"],
        "output_tokens": run_payload["output_tokens"],
        "results": results,
        "campaigns_created": 0,
        "campaigns_approved": 0,
        "order_authority": False,
    }


def proposal_status(connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT filter_status, COUNT(*) AS n FROM proposal_candidates GROUP BY filter_status"
    ).fetchall()
    latest = connection.execute(
        "SELECT payload_json FROM proposal_runs ORDER BY created_at_utc DESC, proposal_run_id DESC LIMIT 1"
    ).fetchone()
    return {
        "proposal_run_count": connection.execute("SELECT COUNT(*) AS n FROM proposal_runs").fetchone()["n"],
        "proposal_candidate_count": connection.execute("SELECT COUNT(*) AS n FROM proposal_candidates").fetchone()["n"],
        "filter_status_counts": {row["filter_status"]: row["n"] for row in rows},
        "latest_run": json.loads(latest["payload_json"]) if latest else None,
        "automatic_campaign_creation": False,
        "automatic_approval": False,
        "order_authority": False,
    }
