import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from fx_research_agent.market_data import register_manifest
from fx_research_agent.motif_discovery import (
    build_feature_arrays,
    build_feature_matrix,
    load_contract,
    run_discovery,
)
from fx_research_agent.storage import connect


def candle(time: datetime, minutes: int, index: int, granularity: str) -> dict:
    base = 1.10 + index * 0.00001 + 0.0002 * np.sin(index / 13.0)
    close = base + 0.00005 * np.sin(index / 5.0)
    end = time + timedelta(minutes=minutes)
    return {
        "instrument": "EUR_USD", "venue": "TEST", "granularity": granularity,
        "candle_time_utc": time.isoformat().replace("+00:00", "Z"),
        "candle_end_time_utc": end.isoformat().replace("+00:00", "Z"),
        "open": base, "high": max(base, close) + 0.0001,
        "low": min(base, close) - 0.0001, "close": close,
        "volume": 100 + index % 17, "range_pips": 2.5,
        "body_pips": abs(close - base) / 0.0001,
        "direction": "BULL" if close >= base else "BEAR",
    }


def series(start: datetime, count: int, minutes: int, granularity: str) -> list[dict]:
    return [candle(start + timedelta(minutes=minutes * index), minutes, index, granularity) for index in range(count)]


def test_contract(path: Path) -> dict:
    source = json.loads((Path(__file__).resolve().parents[1] / "config" / "fx_motif_discovery_v1.json").read_text())
    source["development"] = {
        "start_utc": "2019-01-01T00:00:00Z",
        "end_utc_exclusive": "2019-01-05T00:00:00Z",
        "minimum_rows": 20,
        "minimum_distinct_days": 1,
    }
    source["validation"] = {
        "start_utc": "2019-01-05T00:00:00Z",
        "end_utc_exclusive": "2019-01-06T00:00:00Z",
        "access_policy": "SEALED_NOT_USED_BY_DISCOVERY_V1",
    }
    source["holdout"] = {
        "start_utc": "2019-01-06T00:00:00Z",
        "access_policy": "SEALED_UNTOUCHED_UNTIL_PREDECLARED_CONFIRMATION",
    }
    source["clustering"]["cluster_count"] = 3
    source["clustering"]["maximum_training_rows"] = 1000
    path.write_text(json.dumps(source), encoding="utf-8")
    return source


def candle_groups() -> dict[str, list[dict]]:
    start = datetime(2018, 12, 1, tzinfo=timezone.utc)
    return {
        "M15": series(start, 4200, 15, "M15"),
        "H1": series(start - timedelta(days=20), 1500, 60, "H1"),
        "H4": series(start - timedelta(days=100), 1000, 240, "H4"),
        "D": series(start - timedelta(days=500), 700, 1440, "D"),
    }


class MotifDiscoveryTests(unittest.TestCase):
    def test_future_candle_changes_do_not_change_prior_features(self):
        with tempfile.TemporaryDirectory() as directory:
            contract_path = Path(directory) / "contract.json"
            contract = test_contract(contract_path)
            groups = candle_groups()
            before = build_feature_arrays(groups, contract)
            cutoff = 100
            decision = str(before["times"][cutoff])
            for source_rows in groups.values():
                for row in source_rows:
                    if row["candle_end_time_utc"] > decision:
                        row["close"] += 0.05
                        row["high"] += 0.05
            after = build_feature_arrays(groups, contract)
        np.testing.assert_allclose(before["values"][: cutoff + 1], after["values"][: cutoff + 1])

    def test_contract_rejects_future_outcome_feature(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            payload = test_contract(path)
            payload["feature_names"].append("future_net_r")
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "forbidden"):
                load_contract(path)

    def test_matrix_and_discovery_leave_sealed_splits_uninspected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            test_contract(contract_path)
            inbox = root / "inbox"
            inbox.mkdir()
            groups = candle_groups()
            rows = [row for values in groups.values() for row in values]
            payload = {
                "schema": "FX_HISTORICAL_MARKET_DATA_PAYLOAD_V1",
                "manifest_id": "HIST_1", "instrument": "EUR_USD",
                "data_classes": ["HISTORICAL_COMPLETED_CANDLES"],
                "completed_candles": rows,
                "quality": {"future_outcomes_exported": False, "strategy_labels_exported": False},
            }
            payload_path = inbox / "HIST_1.payload.json.gz"
            with gzip.open(payload_path, "wt", encoding="utf-8") as handle:
                json.dump(payload, handle)
            manifest = {
                "manifest_id": "HIST_1", "schema": "FX_MARKET_DATA_EXPORT_V1",
                "created_at_utc": "2026-10-24T00:00:00Z", "source_system": "TEST",
                "instrument": "EUR_USD", "window_start_utc": rows[0]["candle_time_utc"],
                "window_end_utc": rows[-1]["candle_end_time_utc"],
                "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
                "payload_path": payload_path.name, "freshness_status": "FRESH",
                "gap_status": "COMPLETE", "data_classes": ["HISTORICAL_COMPLETED_CANDLES"],
            }
            manifest_path = inbox / "HIST_1.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            connection = connect(root / "research.sqlite3")
            register_manifest(connection, manifest_path)
            metadata = build_feature_matrix(
                connection, contract_path=contract_path, inbox_dir=inbox,
                output_dir=root / "motif", created_at_utc="2026-10-24T01:00:00Z",
            )
            report = run_discovery(
                connection, contract_path=contract_path,
                matrix_metadata_path=root / "motif" / f"{metadata['artifact_id']}.json",
                output_path=root / "motif" / "report.json",
                created_at_utc="2026-10-24T02:00:00Z",
            )
            repeated = run_discovery(
                connection, contract_path=contract_path,
                matrix_metadata_path=root / "motif" / f"{metadata['artifact_id']}.json",
                output_path=root / "motif" / "report.json",
                created_at_utc="2026-10-24T02:00:00Z",
            )
            connection.close()
        self.assertGreater(report["development_row_count"], 20)
        self.assertEqual(report["cluster_count"], 3)
        self.assertEqual(report["validation_rows_inspected"], 0)
        self.assertEqual(report["holdout_rows_inspected"], 0)
        self.assertEqual(report["future_outcomes_inspected"], 0)
        self.assertFalse(report["profitability_claimed"])
        self.assertEqual(report["fdr_ledger"]["planned_hypothesis_count"], 18)
        self.assertEqual(report["run_id"], repeated["run_id"])


if __name__ == "__main__":
    unittest.main()
