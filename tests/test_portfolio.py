import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.evidence import register_manifest
from fx_research_agent.portfolio import build_portfolio_opportunity_report
from fx_research_agent.storage import initialize


class PortfolioReportTests(unittest.TestCase):
    def test_reports_weekly_cadence_and_overlap_without_execution_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema": "FX_RESEARCH_EVIDENCE_PAYLOAD_V1",
                "manifest_id": "E1",
                "data_classes": ["FORWARD_STRATEGY_SHADOW_EVENTS", "FORWARD_STRATEGY_SHADOW_OUTCOMES"],
                "strategy_shadow_event_facts": [
                    {"event_id": "A", "decision_time_utc": "2026-10-05T10:00:00Z", "mechanism_id": "ORB"},
                    {"event_id": "B", "decision_time_utc": "2026-10-05T12:00:00Z", "mechanism_id": "VWAP"},
                    {"event_id": "C", "decision_time_utc": "2026-10-13T10:00:00Z", "mechanism_id": "ORB"}
                ],
                "strategy_shadow_outcome_facts": [
                    {"outcome_id": "OA", "event_id": "A", "observed_at_utc": "2026-10-05T14:00:00Z"}
                ]
            }
            payload_path = root / "E1.payload.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            manifest = {
                "manifest_id": "E1",
                "schema": "FX_RESEARCH_EVIDENCE_EXPORT_V1",
                "created_at_utc": "2026-10-13T15:00:00Z",
                "source_system": "TEST",
                "instrument": "EUR_USD",
                "window_start_utc": "2026-10-05T10:00:00Z",
                "window_end_utc": "2026-10-13T14:00:00Z",
                "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
                "payload_path": payload_path.name,
                "freshness_status": "FRESH",
                "gap_status": "COMPLETE",
                "data_classes": payload["data_classes"]
            }
            manifest_path = root / "E1.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            register_manifest(connection, manifest_path)
            report = build_portfolio_opportunity_report(connection, root)
        self.assertEqual(report["overall"]["event_count"], 3)
        self.assertEqual(report["overall"]["observed_week_count"], 2)
        self.assertEqual(report["resolved_event_count"], 1)
        self.assertFalse(report["execution_authority"])
        self.assertEqual(report["target"]["qualified_cadence_status"], "NOT_MEASURABLE_FROM_RAW_CANDIDATES")
        self.assertEqual(report["top_trigger_day_overlaps"][0]["shared_trigger_day_count"], 1)


if __name__ == "__main__":
    unittest.main()
