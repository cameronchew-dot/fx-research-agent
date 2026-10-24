#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fx_research_agent.market_data import (  # noqa: E402
    market_data_status,
    register_manifest,
    sync_market_exports,
)
from fx_research_agent.evidence import (  # noqa: E402
    evidence_status,
    register_manifest as register_evidence_manifest,
    sync_evidence_exports,
)
from fx_research_agent.campaigns import (  # noqa: E402
    approve_campaign,
    campaign_data_readiness,
    campaign_report,
    park_campaign,
    register_campaign,
)
from fx_research_agent.experiments import experiment_report, run_campaign  # noqa: E402
from fx_research_agent.automation import (  # noqa: E402
    automation_status,
    refresh_approved_campaigns,
    register_policy,
)
from fx_research_agent.batches import add_campaign_to_batch, batch_report, register_batch  # noqa: E402
from fx_research_agent.proposals import (  # noqa: E402
    load_local_env,
    proposal_status,
    run_proposal_cycle,
)
from fx_research_agent.registry import backlog, import_genesis, review_hypothesis, status  # noqa: E402
from fx_research_agent.storage import connect  # noqa: E402
from fx_research_agent.notifications import (  # noqa: E402
    notification_status,
    notify_gate_crossings,
    notify_ingest_failures,
    notify_proposals_for_review,
)
from fx_research_agent.literature_panels import panel_status  # noqa: E402
from fx_research_agent.financing_sources import audit_paths  # noqa: E402
from fx_research_agent.motif_discovery import (  # noqa: E402
    build_feature_matrix,
    motif_status,
    register_predeclaration,
    run_discovery,
)
from fx_research_agent.motif_evaluation import (  # noqa: E402
    evaluate_development,
    register_evaluation_protocol,
)
from fx_research_agent.context_discovery import (  # noqa: E402
    audit_context_coverage,
    build_context_feature_matrix,
    context_discovery_status,
    run_context_discovery,
)


DEFAULT_DB = ROOT / "data" / "fx_research_agent.sqlite3"
DEFAULT_GENESIS = ROOT / "config" / "genesis_hypotheses.json"
DEFAULT_MARKET_SOURCE = Path("/Users/camcam/eur_bot/exports/fx_research")
DEFAULT_MARKET_INBOX = ROOT / "data" / "inbox"
DEFAULT_MARKET_SYNC_STATUS = ROOT / "data" / "market_ingest_status.json"
DEFAULT_MARKET_DATA_STATUS = ROOT / "data" / "market_data_status.json"
DEFAULT_EVIDENCE_SOURCE = Path("/Users/camcam/eur_agent/exports/fx_research")
DEFAULT_EVIDENCE_INBOX = ROOT / "data" / "evidence_inbox"
DEFAULT_EVIDENCE_SYNC_STATUS = ROOT / "data" / "evidence_ingest_status.json"
DEFAULT_EVIDENCE_STATUS = ROOT / "data" / "research_evidence_status.json"
DEFAULT_CAMPAIGN = ROOT / "config" / "campaigns" / "eur_trend_location_range_forward_v1.json"
DEFAULT_CAMPAIGN_STATUS = ROOT / "data" / "campaign_status.json"
DEFAULT_AUTONOMY_POLICY = ROOT / "config" / "autonomy_policy.json"
DEFAULT_BATCH = ROOT / "config" / "batches" / "eur_forward_batch_v1.json"
DEFAULT_AUTOMATION_STATUS = ROOT / "data" / "automation_status.json"
DEFAULT_PROPOSAL_STATUS = ROOT / "data" / "proposal_status.json"
DEFAULT_FINANCING_SOURCE_CATALOG = ROOT / "config" / "g10_financing_source_catalog.json"
DEFAULT_LITERATURE_PANEL_CONTRACT = ROOT / "config" / "g10_literature_panel_contract.json"
DEFAULT_MOTIF_CONTRACT = ROOT / "config" / "fx_motif_discovery_v1.json"
DEFAULT_MOTIF_PREDECLARATION = ROOT / "config" / "fx_motif_predeclaration_v1.json"
DEFAULT_MOTIF_EVALUATION_PROTOCOL = ROOT / "config" / "fx_motif_evaluation_protocol_v1.json"
DEFAULT_MOTIF_DIR = ROOT / "data" / "motif_discovery"
DEFAULT_CONTEXT_CONTRACT = ROOT / "config" / "fx_context_discovery_v1.json"
DEFAULT_CONTEXT_COVERAGE_STATUS = ROOT / "data" / "context_coverage_status.json"
DEFAULT_CONTEXT_DIR = ROOT / "data" / "context_discovery"
SOURCE_REPO = "https://github.com/cameronchew-dot/eur-usd-agent.git"
SOURCE_COMMIT = "e168603"
SOURCE_PATH = "config/research_hypothesis_registry.json"


def print_json(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    load_local_env(ROOT / ".env")
    parser = argparse.ArgumentParser(description="FX research system-of-record supervisor")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    commands.add_parser("import-genesis")
    commands.add_parser("status")
    commands.add_parser("backlog")
    market = commands.add_parser("register-market-export")
    market.add_argument("manifest", type=Path)
    sync = commands.add_parser("sync-market-exports")
    sync.add_argument("--source-dir", type=Path, default=DEFAULT_MARKET_SOURCE)
    sync.add_argument("--inbox-dir", type=Path, default=DEFAULT_MARKET_INBOX)
    commands.add_parser("market-data-status")
    commands.add_parser("literature-panel-status")
    commands.add_parser("financing-source-status")
    evidence = commands.add_parser("register-research-evidence")
    evidence.add_argument("manifest", type=Path)
    evidence_sync = commands.add_parser("sync-research-evidence")
    evidence_sync.add_argument("--source-dir", type=Path, default=DEFAULT_EVIDENCE_SOURCE)
    evidence_sync.add_argument("--inbox-dir", type=Path, default=DEFAULT_EVIDENCE_INBOX)
    commands.add_parser("research-evidence-status")
    campaign_register = commands.add_parser("register-campaign")
    campaign_register.add_argument("path", nargs="?", type=Path, default=DEFAULT_CAMPAIGN)
    campaign_approve = commands.add_parser("approve-campaign")
    campaign_approve.add_argument("campaign_id")
    campaign_approve.add_argument("--expected-payload-hash", required=True)
    campaign_approve.add_argument("--approved-by", required=True)
    campaign_approve.add_argument("--reason", required=True)
    campaign_park = commands.add_parser("park-campaign")
    campaign_park.add_argument("campaign_id")
    campaign_park.add_argument("--expected-payload-hash", required=True)
    campaign_park.add_argument("--parked-by", required=True)
    campaign_park.add_argument("--reason", required=True)
    campaign_ready = commands.add_parser("campaign-readiness")
    campaign_ready.add_argument("campaign_id")
    commands.add_parser("campaign-status")
    campaign_run = commands.add_parser("run-campaign")
    campaign_run.add_argument("campaign_id")
    campaign_results = commands.add_parser("experiment-status")
    campaign_results.add_argument("campaign_id")
    policy_register = commands.add_parser("register-autonomy-policy")
    policy_register.add_argument("path", nargs="?", type=Path, default=DEFAULT_AUTONOMY_POLICY)
    commands.add_parser("automation-status")
    batch_register = commands.add_parser("register-batch")
    batch_register.add_argument("path", nargs="?", type=Path, default=DEFAULT_BATCH)
    commands.add_parser("batch-status")
    batch_add = commands.add_parser("add-campaign-to-batch")
    batch_add.add_argument("batch_id")
    batch_add.add_argument("campaign_id")
    batch_add.add_argument("--added-by", required=True)
    batch_add.add_argument("--reason", required=True)
    refresh = commands.add_parser("refresh-approved-campaigns")
    refresh.add_argument(
        "--trigger",
        choices=("DAILY_SCHEDULE", "EVIDENCE_SYNC_THRESHOLD_CHECK", "MANUAL"),
        default="MANUAL",
    )
    commands.add_parser("proposal-cycle")
    commands.add_parser("proposal-status")
    commands.add_parser("notification-status")
    review = commands.add_parser("review-hypothesis")
    review.add_argument("hypothesis_id")
    review.add_argument(
        "--decision",
        choices=("APPROVE_FOR_CAMPAIGN_DRAFT", "REJECT", "SUPERSEDE"),
        required=True,
    )
    review.add_argument("--reviewed-by", required=True)
    review.add_argument("--reason", required=True)
    motif_matrix = commands.add_parser("motif-build-matrix")
    motif_matrix.add_argument("--contract", type=Path, default=DEFAULT_MOTIF_CONTRACT)
    motif_matrix.add_argument("--inbox-dir", type=Path, default=DEFAULT_MARKET_INBOX)
    motif_matrix.add_argument("--output-dir", type=Path, default=DEFAULT_MOTIF_DIR)
    motif_discover = commands.add_parser("motif-discover")
    motif_discover.add_argument("--contract", type=Path, default=DEFAULT_MOTIF_CONTRACT)
    motif_discover.add_argument("--matrix-metadata", type=Path, required=True)
    motif_discover.add_argument("--output", type=Path, default=DEFAULT_MOTIF_DIR / "latest_discovery.json")
    commands.add_parser("motif-status")
    motif_predeclare = commands.add_parser("motif-predeclare")
    motif_predeclare.add_argument("--selection", type=Path, default=DEFAULT_MOTIF_PREDECLARATION)
    motif_predeclare.add_argument("--discovery", type=Path, default=DEFAULT_MOTIF_DIR / "latest_discovery.json")
    motif_protocol = commands.add_parser("motif-register-evaluation")
    motif_protocol.add_argument("--protocol", type=Path, default=DEFAULT_MOTIF_EVALUATION_PROTOCOL)
    motif_protocol.add_argument("--predeclaration", type=Path, default=DEFAULT_MOTIF_PREDECLARATION)
    motif_evaluate = commands.add_parser("motif-evaluate-development")
    motif_evaluate.add_argument("--contract", type=Path, default=DEFAULT_MOTIF_CONTRACT)
    motif_evaluate.add_argument("--predeclaration", type=Path, default=DEFAULT_MOTIF_PREDECLARATION)
    motif_evaluate.add_argument("--protocol", type=Path, default=DEFAULT_MOTIF_EVALUATION_PROTOCOL)
    motif_evaluate.add_argument("--discovery", type=Path, default=DEFAULT_MOTIF_DIR / "latest_discovery.json")
    motif_evaluate.add_argument("--matrix-metadata", type=Path, required=True)
    motif_evaluate.add_argument("--inbox-dir", type=Path, default=DEFAULT_MARKET_INBOX)
    motif_evaluate.add_argument("--output-dir", type=Path, default=DEFAULT_MOTIF_DIR)
    context_audit = commands.add_parser("context-coverage-audit")
    context_audit.add_argument("--contract", type=Path, default=DEFAULT_CONTEXT_CONTRACT)
    context_audit.add_argument("--inbox-dir", type=Path, default=DEFAULT_MARKET_INBOX)
    context_matrix = commands.add_parser("context-build-matrix")
    context_matrix.add_argument("--contract", type=Path, default=DEFAULT_CONTEXT_CONTRACT)
    context_matrix.add_argument("--inbox-dir", type=Path, default=DEFAULT_MARKET_INBOX)
    context_matrix.add_argument("--output-dir", type=Path, default=DEFAULT_CONTEXT_DIR)
    context_discover = commands.add_parser("context-discover")
    context_discover.add_argument("--contract", type=Path, default=DEFAULT_CONTEXT_CONTRACT)
    context_discover.add_argument("--matrix-metadata", type=Path, required=True)
    context_discover.add_argument("--output", type=Path, default=DEFAULT_CONTEXT_DIR / "latest_discovery.json")
    commands.add_parser("context-discovery-status")
    args = parser.parse_args()

    with connect(args.db) as connection:
        if args.command == "init-db":
            print_json(status(connection))
        elif args.command == "import-genesis":
            print_json(
                import_genesis(
                    connection,
                    DEFAULT_GENESIS,
                    SOURCE_REPO,
                    SOURCE_COMMIT,
                    SOURCE_PATH,
                )
            )
        elif args.command == "status":
            print_json(status(connection))
        elif args.command == "backlog":
            print_json(backlog(connection))
        elif args.command == "register-market-export":
            print_json(register_manifest(connection, args.manifest))
        elif args.command == "sync-market-exports":
            result = sync_market_exports(connection, args.source_dir, args.inbox_dir)
            notifications = notify_ingest_failures(connection, "MARKET_DATA", result)
            quality = market_data_status(connection)
            write_json_atomic(DEFAULT_MARKET_SYNC_STATUS, result)
            write_json_atomic(DEFAULT_MARKET_DATA_STATUS, quality)
            print_json({"sync": result, "quality": quality, "notifications": notifications})
        elif args.command == "market-data-status":
            result = market_data_status(connection)
            write_json_atomic(DEFAULT_MARKET_DATA_STATUS, result)
            print_json(result)
        elif args.command == "literature-panel-status":
            print_json(panel_status(connection, DEFAULT_MARKET_INBOX))
        elif args.command == "financing-source-status":
            print_json(audit_paths(DEFAULT_FINANCING_SOURCE_CATALOG, DEFAULT_LITERATURE_PANEL_CONTRACT))
        elif args.command == "register-research-evidence":
            print_json(register_evidence_manifest(connection, args.manifest))
        elif args.command == "sync-research-evidence":
            result = sync_evidence_exports(connection, args.source_dir, args.inbox_dir)
            notifications = notify_ingest_failures(connection, "RESEARCH_EVIDENCE", result)
            quality = evidence_status(connection)
            threshold_refresh = None
            if connection.execute("SELECT COUNT(*) AS n FROM autonomy_policies").fetchone()["n"]:
                threshold_refresh = refresh_approved_campaigns(
                    connection,
                    args.inbox_dir,
                    market_inbox=DEFAULT_MARKET_INBOX,
                    trigger="EVIDENCE_SYNC_THRESHOLD_CHECK",
                )
                notifications.extend(notify_gate_crossings(connection, threshold_refresh))
            write_json_atomic(DEFAULT_EVIDENCE_SYNC_STATUS, result)
            write_json_atomic(DEFAULT_EVIDENCE_STATUS, quality)
            print_json({"sync": result, "quality": quality, "threshold_refresh": threshold_refresh, "notifications": notifications})
        elif args.command == "research-evidence-status":
            result = evidence_status(connection)
            write_json_atomic(DEFAULT_EVIDENCE_STATUS, result)
            print_json(result)
        elif args.command == "register-campaign":
            print_json(register_campaign(connection, args.path))
        elif args.command == "approve-campaign":
            print_json(
                approve_campaign(
                    connection,
                    args.campaign_id,
                    expected_payload_hash=args.expected_payload_hash,
                    approved_by=args.approved_by,
                    reason=args.reason,
                )
            )
        elif args.command == "park-campaign":
            print_json(
                park_campaign(
                    connection,
                    args.campaign_id,
                    expected_payload_hash=args.expected_payload_hash,
                    parked_by=args.parked_by,
                    reason=args.reason,
                )
            )
        elif args.command == "campaign-readiness":
            print_json(campaign_data_readiness(connection, args.campaign_id))
        elif args.command == "campaign-status":
            result = campaign_report(connection)
            write_json_atomic(DEFAULT_CAMPAIGN_STATUS, result)
            print_json(result)
        elif args.command == "run-campaign":
            print_json(
                run_campaign(
                    connection,
                    args.campaign_id,
                    DEFAULT_EVIDENCE_INBOX,
                    market_inbox_dir=DEFAULT_MARKET_INBOX,
                )
            )
        elif args.command == "experiment-status":
            print_json(experiment_report(connection, args.campaign_id))
        elif args.command == "register-autonomy-policy":
            print_json(register_policy(connection, args.path))
        elif args.command == "automation-status":
            result = automation_status(connection)
            write_json_atomic(DEFAULT_AUTOMATION_STATUS, result)
            print_json(result)
        elif args.command == "register-batch":
            print_json(register_batch(connection, args.path))
        elif args.command == "batch-status":
            print_json(batch_report(connection))
        elif args.command == "add-campaign-to-batch":
            print_json(
                add_campaign_to_batch(
                    connection,
                    args.batch_id,
                    args.campaign_id,
                    added_by=args.added_by,
                    reason=args.reason,
                )
            )
        elif args.command == "refresh-approved-campaigns":
            result = refresh_approved_campaigns(
                connection,
                DEFAULT_EVIDENCE_INBOX,
                market_inbox=DEFAULT_MARKET_INBOX,
                trigger=args.trigger,
            )
            print_json({**result, "notifications": notify_gate_crossings(connection, result)})
        elif args.command == "proposal-cycle":
            result = run_proposal_cycle(connection)
            notifications = notify_proposals_for_review(connection, result)
            write_json_atomic(DEFAULT_PROPOSAL_STATUS, proposal_status(connection))
            print_json({**result, "notifications": notifications})
        elif args.command == "proposal-status":
            result = proposal_status(connection)
            write_json_atomic(DEFAULT_PROPOSAL_STATUS, result)
            print_json(result)
        elif args.command == "notification-status":
            print_json(notification_status(connection))
        elif args.command == "review-hypothesis":
            print_json(
                review_hypothesis(
                    connection,
                    args.hypothesis_id,
                    decision=args.decision,
                    reviewed_by=args.reviewed_by,
                    reason=args.reason,
                )
            )
        elif args.command == "motif-build-matrix":
            print_json(
                build_feature_matrix(
                    connection,
                    contract_path=args.contract,
                    inbox_dir=args.inbox_dir,
                    output_dir=args.output_dir,
                )
            )
        elif args.command == "motif-discover":
            print_json(
                run_discovery(
                    connection,
                    contract_path=args.contract,
                    matrix_metadata_path=args.matrix_metadata,
                    output_path=args.output,
                )
            )
        elif args.command == "motif-status":
            print_json(motif_status(connection))
        elif args.command == "motif-predeclare":
            print_json(
                register_predeclaration(
                    connection,
                    selection_path=args.selection,
                    discovery_path=args.discovery,
                )
            )
        elif args.command == "motif-register-evaluation":
            print_json(
                register_evaluation_protocol(
                    connection,
                    protocol_path=args.protocol,
                    predeclaration_path=args.predeclaration,
                )
            )
        elif args.command == "motif-evaluate-development":
            print_json(
                evaluate_development(
                    connection,
                    contract_path=args.contract,
                    predeclaration_path=args.predeclaration,
                    protocol_path=args.protocol,
                    discovery_path=args.discovery,
                    matrix_metadata_path=args.matrix_metadata,
                    inbox_dir=args.inbox_dir,
                    output_dir=args.output_dir,
                )
            )
        elif args.command == "context-coverage-audit":
            result = audit_context_coverage(
                connection,
                contract_path=args.contract,
                inbox_dir=args.inbox_dir,
            )
            write_json_atomic(DEFAULT_CONTEXT_COVERAGE_STATUS, result)
            print_json(result)
        elif args.command == "context-build-matrix":
            print_json(
                build_context_feature_matrix(
                    connection,
                    contract_path=args.contract,
                    inbox_dir=args.inbox_dir,
                    output_dir=args.output_dir,
                )
            )
        elif args.command == "context-discover":
            print_json(
                run_context_discovery(
                    connection,
                    contract_path=args.contract,
                    matrix_metadata_path=args.matrix_metadata,
                    output_path=args.output,
                )
            )
        elif args.command == "context-discovery-status":
            print_json(context_discovery_status(connection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

