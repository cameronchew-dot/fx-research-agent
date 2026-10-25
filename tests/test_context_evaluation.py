import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from fx_research_agent.context_evaluation import (
    _trade_outcome,
    load_protocol,
    register_evaluation_protocol,
    register_predeclaration,
)
from fx_research_agent.storage import connect


class ContextEvaluationTests(unittest.TestCase):
    def _files(self, root: Path, *, cluster_id: str = "CONTEXT_A") -> tuple[Path, Path, Path]:
        discovery = {
            "schema": "FX_CONTEXT_DISCOVERY_REPORT_V1",
            "run_id": "RUN_1",
            "matrix_artifact_id": "MATRIX_1",
            "future_outcomes_inspected": 0,
            "profitability_claimed": False,
            "clusters": [{"machine_cluster_id": "CONTEXT_A"}],
        }
        discovery_path = root / "discovery.json"
        discovery_path.write_text(json.dumps(discovery, sort_keys=True), encoding="utf-8")
        predeclaration = {
            "schema": "FX_CONTEXT_PREDECLARATION_V1",
            "predeclaration_id": "PRE_1",
            "predeclared_at_utc": "2026-10-24T00:00:00Z",
            "source_discovery_run_id": "RUN_1",
            "source_matrix_artifact_id": "MATRIX_1",
            "source_discovery_report_sha256": hashlib.sha256(discovery_path.read_bytes()).hexdigest(),
            "selected_contexts": [{"machine_cluster_id": cluster_id, "direction": "LONG"}],
            "execution_geometry": {"horizon_bars": [4, 8, 16]},
            "planned_confirmation_budget": {
                "selected_context_count": 1,
                "horizon_bars": [4, 8, 16],
                "planned_primary_hypothesis_count": 3,
                "correction": "HOLM_BONFERRONI_REQUIRED",
            },
            "authority": {"research_only": True, "paper_or_live_authority": False},
        }
        predeclaration_path = root / "predeclaration.json"
        predeclaration_path.write_text(json.dumps(predeclaration), encoding="utf-8")
        protocol = {
            "schema": "FX_CONTEXT_EVALUATION_PROTOCOL_V1",
            "protocol_id": "PROTOCOL_1",
            "created_at_utc": "2026-10-24T01:00:00Z",
            "predeclaration_id": "PRE_1",
            "predeclaration_file_sha256": hashlib.sha256(predeclaration_path.read_bytes()).hexdigest(),
            "evaluation_split": "DEVELOPMENT_ONLY",
            "significance_test": {
                "method": "ONE_SIDED_PAIRED_SIGN_FLIP_MONTE_CARLO",
                "draw_count": 100,
                "seed": 7,
            },
            "multiple_comparisons": {"method": "HOLM_BONFERRONI"},
            "authority": {"research_only": True, "paper_or_live_authority": False},
        }
        protocol_path = root / "protocol.json"
        protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
        return discovery_path, predeclaration_path, protocol_path

    def test_unknown_context_is_rejected_before_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery, predeclaration, _ = self._files(root, cluster_id="UNKNOWN")
            connection = connect(root / "research.sqlite3")
            with self.assertRaisesRegex(ValueError, "unknown cluster"):
                register_predeclaration(
                    connection,
                    selection_path=predeclaration,
                    discovery_path=discovery,
                )
            connection.close()

    def test_protocol_requires_exact_registered_predeclaration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery, predeclaration, protocol = self._files(root)
            connection = connect(root / "research.sqlite3")
            with self.assertRaisesRegex(ValueError, "registered first"):
                register_evaluation_protocol(
                    connection,
                    protocol_path=protocol,
                    predeclaration_path=predeclaration,
                )
            register_predeclaration(
                connection,
                selection_path=predeclaration,
                discovery_path=discovery,
            )
            result = register_evaluation_protocol(
                connection,
                protocol_path=protocol,
                predeclaration_path=predeclaration,
            )
            connection.close()
        self.assertEqual(result["validation_rows_permitted"], 0)
        self.assertEqual(result["holdout_rows_permitted"], 0)
        self.assertFalse(result["paper_or_live_authority"])

    def test_protocol_rejects_non_development_split(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, predeclaration, protocol = self._files(root)
            payload = json.loads(protocol.read_text(encoding="utf-8"))
            payload["evaluation_split"] = "VALIDATION"
            protocol.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "development-only"):
                load_protocol(protocol, predeclaration)

    def test_same_bar_stop_and_target_is_stop_first_with_eight_pip_floor(self):
        pack = {
            "time": np.arange(20, dtype=float) * 900.0,
            "end": (np.arange(20, dtype=float) + 1.0) * 900.0,
            "open": np.full(20, 1.1000),
            "high": np.full(20, 1.1005),
            "low": np.full(20, 1.0995),
            "close": np.full(20, 1.1000),
            "atr14": np.full(20, 0.0005),
        }
        pack["high"][1] = 1.1020
        pack["low"][1] = 1.0980
        outcome = _trade_outcome(
            pack,
            signal_index=0,
            direction="LONG",
            horizon=4,
            target_r=1.5,
            fixed_cost_pips=1.9,
            development_end=100000.0,
        )
        self.assertEqual(outcome["stop_distance_pips"], 8.0)
        self.assertEqual(outcome["exit_reason"], "STOP")
        self.assertEqual(outcome["gross_r"], -1.0)
        self.assertLess(outcome["net_r"], -1.0)


if __name__ == "__main__":
    unittest.main()
