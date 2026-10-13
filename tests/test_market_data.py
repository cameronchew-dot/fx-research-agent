import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.market_data import validate_manifest


class MarketDataTests(unittest.TestCase):
    def _write_export(self, root: Path, payload):
        payload_path = root / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = {
            "manifest_id": "MANIFEST_1",
            "schema": "FX_MARKET_DATA_EXPORT_V1",
            "created_at_utc": "2026-10-13T00:00:00Z",
            "source_system": "EUR_COLLECTOR",
            "instrument": "EUR_USD",
            "window_start_utc": "2026-10-12T00:00:00Z",
            "window_end_utc": "2026-10-13T00:00:00Z",
            "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
            "payload_path": str(payload_path),
            "freshness_status": "FRESH",
            "gap_status": "COMPLETE",
            "data_classes": ["COMPLETED_CANDLES", "OANDA_QUOTE_PRESSURE_PROXY"],
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_market_only_export_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_export(Path(directory), {"candles": [], "quote_pressure_proxy": []})
            self.assertEqual(validate_manifest(path)["manifest_id"], "MANIFEST_1")

    def test_account_and_order_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_export(Path(directory), {"account_id": "secret", "orders": []})
            with self.assertRaisesRegex(ValueError, "prohibited fields"):
                validate_manifest(path)


if __name__ == "__main__":
    unittest.main()
