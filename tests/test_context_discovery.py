import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.context_discovery import audit_context_coverage, load_contract
from fx_research_agent.market_data import register_manifest
from fx_research_agent.storage import initialize


class ContextDiscoveryTests(unittest.TestCase):
    def _contract(self, root: Path) -> Path:
        path = root / "contract.json"
        path.write_text(json.dumps({
            "schema": "FX_CONTEXT_DISCOVERY_CONTRACT_V1",
            "contract_id": "TEST_CONTEXT_V1",
            "development": {"start_utc": "2020-01-01T00:00:00Z", "end_utc_exclusive": "2020-01-03T00:00:00Z"},
            "required_sources": [
                {"source_id": "EURGBP_M15", "role": "EUR_CROSS_CONFIRMATION", "instrument": "EUR_GBP", "granularity": "M15", "minimum_development_rows": 2, "minimum_distinct_days": 2}
            ],
            "feature_names": ["eurgbp_return_1"],
            "future_outcomes_allowed_in_features": False,
            "authority": {"research_only": True, "paper_or_live_authority": False}
        }), encoding="utf-8")
        return path

    def _register_export(self, connection, inbox: Path, *, include_outcomes: bool = False) -> None:
        payload = {
            "schema": "FX_HISTORICAL_MARKET_DATA_PAYLOAD_V1",
            "quality": {"future_outcomes_exported": include_outcomes, "strategy_labels_exported": False},
            "completed_candles": [
                {"instrument": "EUR_GBP", "granularity": "M15", "candle_time_utc": "2020-01-01T00:00:00Z", "candle_end_time_utc": "2020-01-01T00:15:00Z", "open": 0.85, "high": 0.86, "low": 0.84, "close": 0.855},
                {"instrument": "EUR_GBP", "granularity": "M15", "candle_time_utc": "2020-01-02T00:00:00Z", "candle_end_time_utc": "2020-01-02T00:15:00Z", "open": 0.855, "high": 0.865, "low": 0.845, "close": 0.86},
                {"instrument": "EUR_GBP", "granularity": "M15", "candle_time_utc": "2020-01-03T00:00:00Z", "candle_end_time_utc": "2020-01-03T00:15:00Z", "open": 0.86, "high": 0.87, "low": 0.85, "close": 0.865}
            ]
        }
        payload_path = inbox / "CTX.payload.json.gz"
        with gzip.open(payload_path, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle)
        manifest = {
            "manifest_id": "CTX", "schema": "FX_MARKET_DATA_EXPORT_V1",
            "created_at_utc": "2026-10-24T00:00:00Z", "source_system": "TEST",
            "instrument": "EUR_GBP", "window_start_utc": "2020-01-01T00:00:00Z",
            "window_end_utc": "2020-01-03T00:00:00Z",
            "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
            "payload_path": payload_path.name, "freshness_status": "FRESH", "gap_status": "COMPLETE",
            "data_classes": ["HISTORICAL_COMPLETED_CANDLES"]
        }
        manifest_path = inbox / "CTX.manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        register_manifest(connection, manifest_path)

    def test_coverage_audit_is_development_only_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            self._register_export(connection, root)
            contract = self._contract(root)
            first = audit_context_coverage(connection, contract_path=contract, inbox_dir=root, created_at_utc="2026-10-24T01:00:00Z")
            second = audit_context_coverage(connection, contract_path=contract, inbox_dir=root, created_at_utc="2026-10-25T01:00:00Z")

        self.assertEqual(first["coverage_status"], "READY_FOR_OUTCOME_BLIND_CONTEXT_DISCOVERY")
        self.assertEqual(first["audit_id"], second["audit_id"])
        self.assertEqual(first["created_at_utc"], second["created_at_utc"])
        self.assertEqual(first["source_results"][0]["development_row_count"], 2)
        self.assertTrue(first["safety"]["validation_or_holdout_outcomes_read"] is False)

    def test_outcome_bearing_context_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            self._register_export(connection, root, include_outcomes=True)
            with self.assertRaisesRegex(ValueError, "outcome/label exclusion"):
                audit_context_coverage(connection, contract_path=self._contract(root), inbox_dir=root)

    def test_contract_rejects_future_derived_feature_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            payload = json.loads(contract.read_text(encoding="utf-8"))
            payload["feature_names"] = ["future_net_r"]
            contract.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "forbidden"):
                load_contract(contract)


if __name__ == "__main__":
    unittest.main()
