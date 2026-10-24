import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from fx_research_agent.context_discovery import (
    audit_context_coverage,
    build_context_feature_arrays,
    build_context_feature_matrix,
    context_discovery_status,
    load_contract,
    run_context_discovery,
)
from fx_research_agent.market_data import register_manifest
from fx_research_agent.storage import initialize


class ContextDiscoveryTests(unittest.TestCase):
    def _full_contract(self, root: Path) -> Path:
        source = json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "fx_context_discovery_v1.json").read_text()
        )
        source["development"] = {
            "start_utc": "2019-01-01T00:00:00Z",
            "end_utc_exclusive": "2019-01-06T00:00:00Z",
        }
        for row in source["required_sources"]:
            row["minimum_development_rows"] = 20
            row["minimum_distinct_days"] = 1
        source["clustering"]["cluster_count"] = 3
        source["clustering"]["maximum_training_rows"] = 1000
        path = root / "full-contract.json"
        path.write_text(json.dumps(source), encoding="utf-8")
        return path

    @staticmethod
    def _series(instrument: str, granularity: str, start: datetime, count: int, minutes: int) -> list[dict]:
        rows = []
        for index in range(count):
            time = start + timedelta(minutes=index * minutes)
            base = 1.0 + 0.0001 * index + 0.001 * np.sin(index / 11.0)
            rows.append({
                "instrument": instrument,
                "granularity": granularity,
                "candle_time_utc": time.isoformat().replace("+00:00", "Z"),
                "candle_end_time_utc": (time + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
                "open": base,
                "high": base + 0.001,
                "low": base - 0.001,
                "close": base + 0.0002 * np.cos(index / 7.0),
            })
        return rows

    def _source_rows(self) -> dict[str, list[dict]]:
        start = datetime(2019, 1, 1, tzinfo=timezone.utc)
        specs = {
            "EURUSD_M15": ("EUR_USD", "M15", 480, 15),
            "EURGBP_M15": ("EUR_GBP", "M15", 480, 15),
            "EURJPY_M15": ("EUR_JPY", "M15", 480, 15),
            "XAUUSD_M15": ("XAU_USD", "M15", 480, 15),
            "SPX500_H1": ("SPX500_USD", "H1", 120, 60),
            "NAS100_H1": ("NAS100_USD", "H1", 120, 60),
            "USB10Y_H1": ("USB10Y_USD", "H1", 120, 60),
            "DE10YB_H1": ("DE10YB_EUR", "H1", 120, 60),
        }
        return {
            source_id: self._series(instrument, granularity, start, count, minutes)
            for source_id, (instrument, granularity, count, minutes) in specs.items()
        }

    def _register_sources(self, connection, inbox: Path, sources: dict[str, list[dict]]) -> None:
        for source_id, rows in sources.items():
            payload = {
                "schema": "FX_HISTORICAL_MARKET_DATA_PAYLOAD_V1",
                "quality": {"future_outcomes_exported": False, "strategy_labels_exported": False},
                "completed_candles": rows,
            }
            payload_path = inbox / f"{source_id}.payload.json.gz"
            with gzip.open(payload_path, "wt", encoding="utf-8") as handle:
                json.dump(payload, handle)
            manifest = {
                "manifest_id": source_id,
                "schema": "FX_MARKET_DATA_EXPORT_V1",
                "created_at_utc": "2026-10-24T00:00:00Z",
                "source_system": "TEST",
                "instrument": rows[0]["instrument"],
                "window_start_utc": rows[0]["candle_time_utc"],
                "window_end_utc": rows[-1]["candle_end_time_utc"],
                "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
                "payload_path": payload_path.name,
                "freshness_status": "FRESH",
                "gap_status": "COMPLETE",
                "data_classes": ["HISTORICAL_COMPLETED_CANDLES"],
            }
            manifest_path = inbox / f"{source_id}.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            register_manifest(connection, manifest_path)

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
            connection.close()

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
            connection.close()

    def test_contract_rejects_future_derived_feature_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            payload = json.loads(contract.read_text(encoding="utf-8"))
            payload["feature_names"] = ["future_net_r"]
            contract.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "forbidden"):
                load_contract(contract)

    def test_context_features_are_point_in_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = load_contract(self._full_contract(root))
            sources = self._source_rows()
            before = build_context_feature_arrays(sources, contract)
            cutoff = 100
            decision = str(before["times"][cutoff])
            for rows in sources.values():
                for row in rows:
                    if row["candle_end_time_utc"] > decision:
                        row["close"] += 0.25
            after = build_context_feature_arrays(sources, contract)

        np.testing.assert_allclose(before["values"][: cutoff + 1], after["values"][: cutoff + 1])

    def test_matrix_and_discovery_are_descriptive_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            self._register_sources(connection, inbox, self._source_rows())
            contract = self._full_contract(root)
            metadata = build_context_feature_matrix(
                connection,
                contract_path=contract,
                inbox_dir=inbox,
                output_dir=root / "context",
                created_at_utc="2026-10-24T01:00:00Z",
            )
            report = run_context_discovery(
                connection,
                contract_path=contract,
                matrix_metadata_path=root / "context" / f"{metadata['artifact_id']}.json",
                output_path=root / "context" / "latest.json",
                created_at_utc="2026-10-24T02:00:00Z",
            )
            repeated = run_context_discovery(
                connection,
                contract_path=contract,
                matrix_metadata_path=root / "context" / f"{metadata['artifact_id']}.json",
                output_path=root / "context" / "latest.json",
                created_at_utc="2026-10-25T02:00:00Z",
            )
            status = context_discovery_status(connection)
            connection.close()

        self.assertGreater(metadata["development_row_count"], 100)
        self.assertEqual(metadata["validation_rows_included"], 0)
        self.assertEqual(report["cluster_count"], 3)
        self.assertEqual(report["future_outcomes_inspected"], 0)
        self.assertEqual(report["comparisons_executed"], 0)
        self.assertFalse(report["direction_or_geometry_assigned"])
        self.assertEqual(report["run_id"], repeated["run_id"])
        self.assertEqual(status["context_discovery_status"], "DESCRIBED_RESEARCH_ONLY")


if __name__ == "__main__":
    unittest.main()
