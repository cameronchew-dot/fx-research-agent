import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.databento_package import import_package
from fx_research_agent.futures_context import futures_context_status
from fx_research_agent.market_data import register_manifest
from fx_research_agent.storage import initialize


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DatabentoPackageTests(unittest.TestCase):
    def test_import_preserves_source_and_declares_degraded_date_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            data_file = source / "glbx.ohlcv-1m.dbn.zst"
            data_file.write_bytes(b"immutable-provider-data")
            (source / "condition.json").write_text(json.dumps([
                {"date": "2020-01-01", "condition": "available"},
                {"date": "2020-01-02", "condition": "degraded"},
            ]), encoding="utf-8")
            metadata = {
                "job_id": "GLBX-TEST",
                "query": {
                    "dataset": "GLBX.MDP3", "schema": "ohlcv-1m", "symbols": ["6E.FUT"],
                    "start": 1577836800000000000, "end": 1578009600000000000,
                    "encoding": "dbn", "compression": "zstd",
                },
            }
            (source / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            manifest_files = []
            for path in (source / "condition.json", source / "metadata.json", data_file):
                manifest_files.append({"filename": path.name, "size": path.stat().st_size, "hash": f"sha256:{digest(path)}"})
            (source / "manifest.json").write_text(json.dumps({"job_id": "GLBX-TEST", "files": manifest_files}), encoding="utf-8")

            imported = import_package(source, root / "external")
            generated_manifest = Path(imported["manifest_path"])
            payload = json.loads((generated_manifest.parent / "GLBX-TEST.package-index.payload.json").read_text())
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            registered = register_manifest(connection, generated_manifest)
            status = futures_context_status(connection, Path("config/cme_fx_context_contract.json"))

        self.assertEqual(imported["excluded_date_count"], 1)
        self.assertEqual(payload["quality"]["excluded_dates"], ["2020-01-02"])
        self.assertTrue(registered["usable_for_testing"])
        self.assertEqual(status["context_status"], "READY")

    def test_declared_exclusions_cannot_unlock_unvalidated_generic_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload_path = root / "generic.payload.json"
            payload_path.write_text(json.dumps({"rows": []}), encoding="utf-8")
            manifest_path = root / "generic.manifest.json"
            manifest_path.write_text(json.dumps({
                "manifest_id": "GENERIC-TEST",
                "schema": "FX_MARKET_DATA_EXPORT_V1",
                "created_at_utc": "2020-01-03T00:00:00Z",
                "source_system": "GENERIC",
                "instrument": "EUR_USD",
                "window_start_utc": "2020-01-01T00:00:00Z",
                "window_end_utc": "2020-01-03T00:00:00Z",
                "payload_sha256": digest(payload_path),
                "payload_path": payload_path.name,
                "freshness_status": "FRESH",
                "gap_status": "COMPLETE_WITH_DECLARED_EXCLUSIONS",
                "data_classes": ["COMPLETED_CANDLES"],
            }), encoding="utf-8")
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            registered = register_manifest(connection, manifest_path)

        self.assertFalse(registered["usable_for_testing"])


if __name__ == "__main__":
    unittest.main()
