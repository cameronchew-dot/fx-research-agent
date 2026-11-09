from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_report(*, root: Path, contract_path: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    source_path = root / str(contract["source_result"])
    source = json.loads(source_path.read_text(encoding="utf-8"))
    hypotheses = {str(row["treatment"]): row for row in source["hypotheses"]}
    populations = []
    for population_id, source_key in contract["populations"].items():
        if source_key == "unfiltered_spot_setup":
            metrics = source[source_key]
            survivor = False
            gate_blocks = ["NEGATIVE_ABSOLUTE_EXPECTANCY"]
        else:
            hypothesis = hypotheses[source_key]
            metrics = hypothesis["primary"]
            survivor = bool(hypothesis["development_survivor"])
            gate_blocks = list(hypothesis["gate_blocks"])
        populations.append(
            {
                "population_id": population_id,
                "source_population": source_key,
                "event_count": int(metrics["event_count"]),
                "average_net_r": float(metrics["average_net_r"]),
                "median_net_r": float(metrics["median_net_r"]),
                "positive_net_r_rate": float(metrics["positive_net_r_rate"]),
                "positive_month_rate": float(metrics["positive_month_rate"]),
                "worst_month_average_net_r": float(
                    metrics["worst_month_average_net_r"]
                ),
                "development_survivor": survivor,
                "gate_blocks": gate_blocks,
            }
        )
    cme_populations = [
        row for row in populations if row["population_id"] != "OANDA_REPRODUCIBLE_SPOT_ONLY"
    ]
    purchase_supported = any(
        row["development_survivor"] and row["average_net_r"] > 0.0
        for row in cme_populations
    )
    return {
        "schema": "FX_RESEARCH_CME_LIVE_DATA_COST_ABLATION_REPORT_V1",
        "ablation_id": contract["ablation_id"],
        "generated_at_utc": _utc_now(),
        "status": "NO_EVIDENCE_TO_PURCHASE_LIVE_CME" if not purchase_supported else "HUMAN_REVIEW_REQUIRED",
        "diagnostic_only": True,
        "development_partition_only": True,
        "validation_rows_inspected": int(source["validation_rows_inspected"]),
        "dated_confirmation_rows_inspected": int(source["dated_confirmation_rows_inspected"]),
        "populations": populations,
        "live_cme_purchase_supported": purchase_supported,
        "recommendation": (
            "DO_NOT_BUY_LIVE_CME; CONTINUE OANDA_REPRODUCIBLE_FORWARD_CONTEXT"
            if not purchase_supported
            else "REVIEW_INCREMENTAL_VALUE_AND_COST_BEFORE_PURCHASE"
        ),
        "reason": (
            "No CME-dependent population had positive absolute expectancy or survived the locked development gates."
            if not purchase_supported
            else "At least one CME-dependent population met the predeclared purchase criteria."
        ),
        "automatic_purchase_allowed": False,
        "automatic_downstream_export_allowed": False,
        "paper_or_live_authority": False,
        "provenance": {
            "contract_path": str(contract_path.relative_to(root)),
            "contract_sha256": _hash(contract_path),
            "source_result": str(source_path.relative_to(root)),
            "source_result_sha256": _hash(source_path),
            "source_campaign": contract["source_campaign"],
        },
        "limitations": list(contract["limitations"]),
    }


def write_report(*, root: Path, contract_path: Path, output_path: Path) -> dict[str, Any]:
    report = build_report(root=root, contract_path=contract_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
