import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.literature_panels import (
    EXPECTED_CURRENCY_BY_INSTRUMENT,
    PANEL_DATA_CLASSES,
    panel_status,
)
from fx_research_agent.market_data import register_manifest, validate_manifest
from fx_research_agent.storage import initialize


class LiteraturePanelTests(unittest.TestCase):
    def _write_panel(
        self,
        root: Path,
        instrument: str,
        *,
        months: int = 2,
        financing_source: str = "OBSERVED_ONE_MONTH_FORWARD_POINTS",
        break_arithmetic: bool = False,
    ) -> Path:
        currency = EXPECTED_CURRENCY_BY_INSTRUMENT[instrument]
        rows = []
        for index in range(months):
            spot = 0.01 + index * 0.0001
            financing = -0.001
            excess = spot + financing + (0.1 if break_arithmetic else 0.0)
            cost = 0.0002
            rows.append(
                {
                    "month_end_utc": f"2020-{index + 1:02d}-28T22:00:00Z",
                    "instrument": instrument,
                    "normalized_currency": currency,
                    "normalized_spot_return": spot,
                    "financing_return": financing,
                    "financing_source_type": financing_source,
                    "gross_excess_return": excess,
                    "round_trip_cost_return": cost,
                    "transaction_cost_source": "HISTORICAL_BID_ASK",
                    "net_excess_return": excess - cost,
                }
            )
        payload = {
            "schema": "FX_G10_MONTHLY_EXCESS_RETURN_PANEL_V1",
            "instrument": instrument,
            "normalized_currency": currency,
            "quote_normalization": "USD_VALUE_OF_ONE_UNIT_FOREIGN_CURRENCY",
            "monthly_rows": rows,
        }
        payload_path = root / f"{instrument}.payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        manifest_id = f"G10_{instrument}"
        manifest = {
            "manifest_id": manifest_id,
            "schema": "FX_MARKET_DATA_EXPORT_V1",
            "created_at_utc": "2026-10-16T20:00:00Z",
            "source_system": "G10_LITERATURE_PANEL_BUILDER",
            "instrument": instrument,
            "window_start_utc": rows[0]["month_end_utc"],
            "window_end_utc": rows[-1]["month_end_utc"],
            "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
            "payload_path": payload_path.name,
            "freshness_status": "FRESH",
            "gap_status": "COMPLETE",
            "data_classes": sorted(PANEL_DATA_CLASSES),
        }
        manifest_path = root / f"{manifest_id}.manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_valid_observed_forward_panel_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_panel(Path(directory), "EUR_USD")
            self.assertEqual(validate_manifest(path)["instrument"], "EUR_USD")

    def test_inferred_financing_and_bad_arithmetic_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inferred = self._write_panel(root, "EUR_USD", financing_source="ZERO_FILLED")
            with self.assertRaisesRegex(ValueError, "must be observed"):
                validate_manifest(inferred)
        with tempfile.TemporaryDirectory() as directory:
            broken = self._write_panel(Path(directory), "EUR_USD", break_arithmetic=True)
            with self.assertRaisesRegex(ValueError, "arithmetic mismatch"):
                validate_manifest(broken)

    def test_status_requires_a_complete_common_panel(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory)
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            for instrument in EXPECTED_CURRENCY_BY_INSTRUMENT:
                register_manifest(connection, self._write_panel(inbox, instrument))
            status = panel_status(connection, inbox)
            connection.close()
        self.assertEqual(status["panel_status"], "BLOCKED")
        self.assertEqual(status["common_month_count"], 2)
        self.assertEqual(status["missing_instruments"], [])
        self.assertFalse(status["spot_only_allowed"])


if __name__ == "__main__":
    unittest.main()
