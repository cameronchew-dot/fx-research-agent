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
    review = commands.add_parser("review-hypothesis")
    review.add_argument("hypothesis_id")
    review.add_argument(
        "--decision",
        choices=("APPROVE_FOR_CAMPAIGN_DRAFT", "REJECT", "SUPERSEDE"),
        required=True,
    )
    review.add_argument("--reviewed-by", required=True)
    review.add_argument("--reason", required=True)
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
            quality = market_data_status(connection)
            write_json_atomic(DEFAULT_MARKET_SYNC_STATUS, result)
            write_json_atomic(DEFAULT_MARKET_DATA_STATUS, quality)
            print_json({"sync": result, "quality": quality})
        elif args.command == "market-data-status":
            result = market_data_status(connection)
            write_json_atomic(DEFAULT_MARKET_DATA_STATUS, result)
            print_json(result)
        elif args.command == "register-research-evidence":
            print_json(register_evidence_manifest(connection, args.manifest))
        elif args.command == "sync-research-evidence":
            result = sync_evidence_exports(connection, args.source_dir, args.inbox_dir)
            quality = evidence_status(connection)
            threshold_refresh = None
            if connection.execute("SELECT COUNT(*) AS n FROM autonomy_policies").fetchone()["n"]:
                threshold_refresh = refresh_approved_campaigns(
                    connection,
                    args.inbox_dir,
                    trigger="EVIDENCE_SYNC_THRESHOLD_CHECK",
                )
            write_json_atomic(DEFAULT_EVIDENCE_SYNC_STATUS, result)
            write_json_atomic(DEFAULT_EVIDENCE_STATUS, quality)
            print_json({"sync": result, "quality": quality, "threshold_refresh": threshold_refresh})
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
        elif args.command == "campaign-readiness":
            print_json(campaign_data_readiness(connection, args.campaign_id))
        elif args.command == "campaign-status":
            result = campaign_report(connection)
            write_json_atomic(DEFAULT_CAMPAIGN_STATUS, result)
            print_json(result)
        elif args.command == "run-campaign":
            print_json(run_campaign(connection, args.campaign_id, DEFAULT_EVIDENCE_INBOX))
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
            print_json(
                refresh_approved_campaigns(
                    connection,
                    DEFAULT_EVIDENCE_INBOX,
                    trigger=args.trigger,
                )
            )
        elif args.command == "proposal-cycle":
            result = run_proposal_cycle(connection)
            write_json_atomic(DEFAULT_PROPOSAL_STATUS, proposal_status(connection))
            print_json(result)
        elif args.command == "proposal-status":
            result = proposal_status(connection)
            write_json_atomic(DEFAULT_PROPOSAL_STATUS, result)
            print_json(result)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

