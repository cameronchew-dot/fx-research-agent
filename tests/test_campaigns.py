import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.campaigns import (
    approve_campaign,
    campaign_data_readiness,
    register_campaign,
)
from fx_research_agent.storage import initialize


def campaign_payload() -> dict:
    return {
        "schema": "FX_RESEARCH_CAMPAIGN_V1",
        "campaign_id": "CAMPAIGN_1",
        "hypothesis_id": "HYP_1",
        "created_at_utc": "2026-10-13T00:00:00Z",
        "state": "DRAFT",
        "title": "Locked test campaign",
        "instrument": "EUR_USD",
        "mechanism_class": "TEST",
        "research_question": "Does the treatment improve net R?",
        "null_hypothesis": "No lift",
        "required_data_classes": ["COMPLETED_CANDLES", "FORWARD_OUTCOMES"],
        "population": {"source": "FORWARD"},
        "independence_unit": {"unit": "EPISODE"},
        "exact_specification": {"threshold": 2.0},
        "controls": [{"control_id": "CONTROL_1", "definition": "Complement"}],
        "metrics": {"primary": "AVERAGE_NET_R_LIFT"},
        "review_gates": {"minimum_n": 30},
        "multiple_comparisons_policy": {"confirmatory_slice_count": 1},
        "stopping_rules": {"no_early_success_declaration": True},
        "authority": {
            "automatic_approval": False,
            "automatic_execution": False,
            "downstream_activation": False,
            "order_authority": False,
        },
    }


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        initialize(self.connection)
        hypothesis = {"hypothesis_id": "HYP_1", "state": "PROPOSED"}
        self.connection.execute(
            "INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?)",
            ("HYP_1", "hash", json.dumps(hypothesis), "repo", "commit", "path", "2026-10-13T00:00:00Z"),
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def _path(self, root: Path) -> Path:
        path = root / "campaign.json"
        path.write_text(json.dumps(campaign_payload()), encoding="utf-8")
        return path

    def test_draft_registration_is_idempotent_and_never_auto_approves(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._path(Path(directory))
            first = register_campaign(self.connection, path)
            second = register_campaign(self.connection, path)
        self.assertTrue(first["inserted"])
        self.assertFalse(second["inserted"])
        self.assertEqual(first["state"], "DRAFT")
        self.assertFalse(first["automatic_approval"])

    def test_approval_requires_exact_hash_and_named_human(self):
        with tempfile.TemporaryDirectory() as directory:
            registered = register_campaign(self.connection, self._path(Path(directory)))
        with self.assertRaisesRegex(ValueError, "does not match"):
            approve_campaign(self.connection, "CAMPAIGN_1", expected_payload_hash="wrong", approved_by="CAMERON", reason="reviewed")
        with self.assertRaisesRegex(ValueError, "named human"):
            approve_campaign(self.connection, "CAMPAIGN_1", expected_payload_hash=registered["campaign_payload_hash"], approved_by="AGENT", reason="reviewed")
        result = approve_campaign(
            self.connection,
            "CAMPAIGN_1",
            expected_payload_hash=registered["campaign_payload_hash"],
            approved_by="CAMERON",
            reason="Exact specification reviewed",
            approved_at_utc="2026-10-13T01:00:00Z",
        )
        self.assertEqual(result["state"], "APPROVED")
        self.assertFalse(result["automatic_execution"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM experiment_specs").fetchone()[0], 1)

    def test_readiness_reports_missing_classes_and_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            register_campaign(self.connection, self._path(Path(directory)))
        readiness = campaign_data_readiness(self.connection, "CAMPAIGN_1")
        self.assertEqual(readiness["readiness_status"], "BLOCKED")
        self.assertIn("campaign_not_human_approved", readiness["blocks"])
        self.assertIn("FORWARD_OUTCOMES", readiness["missing_data_classes"])

    def test_readiness_combines_market_and_forward_evidence_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            registered = register_campaign(self.connection, self._path(Path(directory)))
        market = {
            "instrument": "EUR_USD",
            "data_classes": ["COMPLETED_CANDLES"],
            "window_start_utc": "2026-10-01T00:00:00Z",
            "window_end_utc": "2026-10-13T00:00:00Z",
        }
        evidence = {
            "instrument": "EUR_USD",
            "data_classes": ["FORWARD_OUTCOMES"],
            "window_start_utc": "2026-10-10T00:00:00Z",
            "window_end_utc": "2026-10-13T00:00:00Z",
        }
        for table, manifest_id, payload in (
            ("market_data_manifests", "M1", market),
            ("evidence_manifests", "E1", evidence),
        ):
            self.connection.execute(
                f"INSERT INTO {table} VALUES (?,?,?,?,?)",
                (manifest_id, manifest_id, json.dumps(payload), "2026-10-13T00:00:00Z", 1),
            )
        self.connection.commit()
        approve_campaign(
            self.connection,
            "CAMPAIGN_1",
            expected_payload_hash=registered["campaign_payload_hash"],
            approved_by="CAMERON",
            reason="Exact specification reviewed",
            approved_at_utc="2026-10-13T01:00:00Z",
        )
        readiness = campaign_data_readiness(self.connection, "CAMPAIGN_1")
        self.assertEqual(readiness["readiness_status"], "READY")
        self.assertEqual(readiness["missing_data_classes"], [])

    def test_multi_instrument_readiness_requires_every_instrument(self):
        payload = campaign_payload()
        payload["instrument"] = "G10_PANEL"
        payload["instruments"] = ["EUR_USD", "USD_JPY"]
        payload["required_data_classes"] = ["COMPLETED_CANDLES"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            registered = register_campaign(self.connection, path)
        self.connection.execute(
            "INSERT INTO market_data_manifests VALUES (?,?,?,?,?)",
            (
                "M_EUR",
                "hash-eur",
                json.dumps({
                    "instrument": "EUR_USD",
                    "data_classes": ["COMPLETED_CANDLES"],
                    "window_start_utc": "2026-01-01T00:00:00Z",
                    "window_end_utc": "2026-10-01T00:00:00Z",
                }),
                "2026-10-13T00:00:00Z",
                1,
            ),
        )
        self.connection.commit()
        approve_campaign(
            self.connection,
            "CAMPAIGN_1",
            expected_payload_hash=registered["campaign_payload_hash"],
            approved_by="CAMERON",
            reason="Exact specification reviewed",
            approved_at_utc="2026-10-13T01:00:00Z",
        )
        blocked = campaign_data_readiness(self.connection, "CAMPAIGN_1")
        self.assertEqual(blocked["readiness_status"], "BLOCKED")
        self.assertEqual(blocked["missing_instruments"], ["USD_JPY"])
        self.connection.execute(
            "INSERT INTO market_data_manifests VALUES (?,?,?,?,?)",
            (
                "M_JPY",
                "hash-jpy",
                json.dumps({
                    "instrument": "USD_JPY",
                    "data_classes": ["COMPLETED_CANDLES"],
                    "window_start_utc": "2026-01-01T00:00:00Z",
                    "window_end_utc": "2026-10-01T00:00:00Z",
                }),
                "2026-10-13T00:00:00Z",
                1,
            ),
        )
        self.connection.commit()
        ready = campaign_data_readiness(self.connection, "CAMPAIGN_1")
        self.assertEqual(ready["readiness_status"], "READY")
        self.assertEqual(ready["missing_instruments"], [])


if __name__ == "__main__":
    unittest.main()
