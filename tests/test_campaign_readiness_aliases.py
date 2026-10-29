import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.campaigns import approve_campaign, campaign_data_readiness, register_campaign
from fx_research_agent.storage import initialize


class CampaignReadinessAliasTests(unittest.TestCase):
    def test_historical_candles_satisfy_completed_candle_requirement(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        initialize(connection)
        hypothesis = {"hypothesis_id": "HYP_ALIAS", "state": "PROPOSED"}
        connection.execute(
            "INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?)",
            ("HYP_ALIAS", "hash", json.dumps(hypothesis), "repo", "commit", "path", "2026-10-13T00:00:00Z")
        )
        campaign = {
            "schema": "FX_RESEARCH_CAMPAIGN_V1",
            "campaign_id": "CAMPAIGN_ALIAS",
            "hypothesis_id": "HYP_ALIAS",
            "created_at_utc": "2026-10-13T00:00:00Z",
            "state": "DRAFT",
            "title": "Alias test",
            "instrument": "AUD_USD",
            "mechanism_class": "TEST",
            "research_question": "Are candles available?",
            "null_hypothesis": "No",
            "required_data_classes": ["COMPLETED_CANDLES"],
            "population": {"source": "FORWARD"},
            "independence_unit": {"unit": "EPISODE"},
            "exact_specification": {"threshold": 1},
            "controls": [{"control_id": "C1", "definition": "Control"}],
            "metrics": {"primary": "AVERAGE_NET_R"},
            "review_gates": {"minimum_n": 1},
            "multiple_comparisons_policy": {"count": 1},
            "stopping_rules": {"locked": True},
            "authority": {
                "automatic_approval": False,
                "automatic_execution": False,
                "downstream_activation": False,
                "order_authority": False
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            path.write_text(json.dumps(campaign), encoding="utf-8")
            registered = register_campaign(connection, path)
        approve_campaign(
            connection,
            "CAMPAIGN_ALIAS",
            expected_payload_hash=registered["campaign_payload_hash"],
            approved_by="CAMERON",
            reason="test"
        )
        manifest = {
            "instrument": "AUD_USD",
            "data_classes": ["HISTORICAL_COMPLETED_CANDLES"],
            "window_start_utc": "2020-01-01T00:00:00Z",
            "window_end_utc": "2026-01-01T00:00:00Z"
        }
        connection.execute(
            "INSERT INTO market_data_manifests VALUES (?,?,?,?,?)",
            ("M1", "hash", json.dumps(manifest), "2026-01-01T00:00:00Z", 1)
        )
        readiness = campaign_data_readiness(connection, "CAMPAIGN_ALIAS")
        self.assertEqual(readiness["missing_data_classes"], [])
        self.assertEqual(readiness["readiness_status"], "READY")


if __name__ == "__main__":
    unittest.main()
