import json
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.financing_sources import audit_catalog, load_catalog


ROOT = Path(__file__).resolve().parents[1]


class FinancingSourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / "config" / "g10_financing_source_catalog.json").read_text())
        self.contract = json.loads((ROOT / "config" / "g10_literature_panel_contract.json").read_text())

    def test_committed_catalog_fails_closed(self):
        result = audit_catalog(self.catalog, self.contract)
        self.assertEqual(result["status"], "BLOCKED_SOURCE_ACQUISITION")
        self.assertFalse(result["campaign_4_data_ready"])
        self.assertFalse(result["campaign_5_carry_predeclaration_allowed"])
        self.assertIn("JFE_MENKHOFF_REPLICATION_WORKBOOK", result["benchmark_only_sources"])
        self.assertIn("BBI_REUTERS_DATASTREAM_ORIGINAL_STUDY", result["financing_input_candidates"])

    def test_only_complete_checksummed_panel_can_unlock(self):
        qualifying = {
            "source_id": "ACQUIRED_PANEL",
            "campaign_role": "COMPLETE_CAMPAIGN_PANEL",
            "access_status": "ACQUIRED_AND_CHECKSUMMED",
            "raw_currency_level_rows": True,
            "financing_source_type": "OBSERVED_ONE_MONTH_FORWARD_POINTS",
            "transaction_cost_source": "HISTORICAL_BID_ASK",
            "instruments": self.contract["instruments"],
            "common_month_count": 240,
            "artifact_sha256": "a" * 64,
            "immutable_lineage": True,
        }
        result = audit_catalog({"schema": self.catalog["schema"], "sources": [qualifying]}, self.contract)
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["campaign_4_data_ready"])
        self.assertTrue(result["campaign_5_carry_predeclaration_allowed"])

    def test_catalog_rejects_duplicate_source_ids(self):
        payload = {"schema": self.catalog["schema"], "sources": [self.catalog["sources"][0]] * 2}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_catalog(path)


if __name__ == "__main__":
    unittest.main()
