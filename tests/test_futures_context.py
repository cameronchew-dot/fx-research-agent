import json
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.futures_context import futures_context_status, load_contract, package_csv_export
from fx_research_agent.market_data import register_manifest, validate_manifest
from fx_research_agent.storage import initialize


class FuturesContextTests(unittest.TestCase):
    def test_unconfigured_contract_is_inert(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "CME_FX_CONTEXT_CONTRACT_V1",
                        "products": [{"canonical_product": "6E", "spot_instrument": "EUR_USD"}],
                        "primary_phase_id": "BASELINE",
                        "activation_phases": [{
                            "phase_id": "BASELINE",
                            "required_products": ["6E"],
                            "required_data_classes": ["CME_FX_TRADES"],
                        }],
                        "authority": {"context_only": True, "execution_authority": False}
                    }
                ),
                encoding="utf-8"
            )
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            loaded = load_contract(path)
            status = futures_context_status(connection, path)
        self.assertEqual(loaded["schema"], "CME_FX_CONTEXT_CONTRACT_V1")
        self.assertEqual(status["context_status"], "UNCONFIGURED")
        self.assertFalse(status["automatic_signal_or_execution_authority"])

    def test_csv_packager_creates_valid_immutable_export_and_phase_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "6e.csv"
            csv_path.write_text(
                "window_start_utc,window_end_utc,open,high,low,close,volume,trade_count,open_interest,aggressive_buy_volume,aggressive_sell_volume\n"
                "2026-10-01T00:00:00Z,2026-10-01T00:01:00Z,1.17,1.18,1.16,1.175,100,20,5000,60,40\n",
                encoding="utf-8",
            )
            result = package_csv_export(
                csv_path,
                root / "out",
                product="6E",
                provider="TEST_PROVIDER",
                source_symbol="6E.c.0",
                contract_mode="CONTINUOUS",
                roll_method="VOLUME_SWITCH",
                price_adjustment="BACK_ADJUSTED",
                aggressor_side_method="PROVIDER_SUPPLIED",
            )
            manifest_path = Path(result["manifest_path"])
            self.assertEqual(validate_manifest(manifest_path)["instrument"], "6E")
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            register_manifest(connection, manifest_path)
            status = futures_context_status(connection, Path("config/cme_fx_context_contract.json"))
        self.assertEqual(status["context_status"], "READY")
        self.assertTrue(status["true_cvd_ready"])
        self.assertEqual(status["full_product_coverage_status"], "UNCONFIGURED")

    def test_aggressor_class_cannot_be_declared_without_aggressor_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema": "CME_FX_CONTEXT_EXPORT_V1",
                "canonical_product": "6E",
                "source_provider": "TEST_PROVIDER",
                "source_symbol": "6E",
                "aggressor_side_method": "NONE",
                "contract_metadata": {
                    "contract_mode": "SINGLE_CONTRACT",
                    "roll_method": "NONE",
                    "price_adjustment": "NONE",
                },
                "bars": [{
                    "window_start_utc": "2026-10-01T00:00:00Z",
                    "window_end_utc": "2026-10-01T00:01:00Z",
                    "open": 1.17, "high": 1.18, "low": 1.16, "close": 1.175,
                    "volume": 100, "trade_count": 20,
                }],
            }
            payload_path = root / "payload.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            manifest = {
                "manifest_id": "BAD_CVD",
                "schema": "FX_MARKET_DATA_EXPORT_V1",
                "created_at_utc": "2026-10-01T01:00:00Z",
                "source_system": "TEST",
                "instrument": "6E",
                "window_start_utc": "2026-10-01T00:00:00Z",
                "window_end_utc": "2026-10-01T00:01:00Z",
                "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
                "payload_path": payload_path.name,
                "freshness_status": "FRESH",
                "gap_status": "COMPLETE",
                "data_classes": ["CME_FX_BARS", "CME_FX_AGGRESSOR_IMBALANCE"],
                "provider_provenance": {
                    "provider": "TEST_PROVIDER",
                    "source_symbol": "6E",
                    "canonical_product": "6E",
                    "aggressor_side_method": "NONE",
                },
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "aggressor imbalance"):
                validate_manifest(manifest_path)


if __name__ == "__main__":
    unittest.main()
