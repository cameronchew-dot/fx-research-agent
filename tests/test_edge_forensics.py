import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.edge_forensics import build_cross_system_edge_forensics
from fx_research_agent.storage import initialize


class EdgeForensicsTests(unittest.TestCase):
    def setUp(self):
        self.research = sqlite3.connect(":memory:")
        self.research.row_factory = sqlite3.Row
        initialize(self.research)
        payload = {
            "mechanism_class": "TEST_MECHANISM",
            "metrics": {
                "development": {
                    "signal": {"count": 40, "avg_net_r": -0.1, "positive_rate": 0.4},
                    "oos": {"avg_net_r": -0.2},
                    "edge_over_best_control_r": -0.05,
                    "cost_stress": {"3.0": {"avg_net_r": -0.3}},
                    "failed_gates": [
                        "minimum_avg_net_r",
                        "minimum_chronological_oos_avg_net_r",
                        "minimum_edge_over_best_control_r",
                        "minimum_worst_cost_avg_net_r",
                    ],
                }
            },
        }
        self.research.execute(
            "INSERT INTO external_result_manifests "
            "(package_id,payload_hash,payload_json,imported_at_utc) VALUES (?,?,?,?)",
            ("PKG", "hash", "{}", "2026-01-01T00:00:00Z"),
        )
        self.research.execute(
            "INSERT INTO external_research_results "
            "(result_id,payload_hash,payload_json,package_id,hypothesis_id,instrument,"
            "result_status,knowable_at_utc,imported_at_utc) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "RESULT_TEST",
                "hash",
                json.dumps(payload),
                "PKG",
                "TEST_HYPOTHESIS",
                "AUD_USD",
                "FAIL_DEVELOPMENT",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        self.research.commit()

    def tearDown(self):
        self.research.close()

    @staticmethod
    def _agent_db(path: Path) -> None:
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE candidates(candidate_id TEXT PRIMARY KEY, mechanism_class TEXT,
              decision_time_utc TEXT);
            CREATE TABLE agent_decisions(decision_id TEXT PRIMARY KEY, candidate_id TEXT,
              arm_id TEXT, decided_at_utc TEXT);
            CREATE TABLE decision_outcomes(decision_id TEXT PRIMARY KEY, realized_net_r REAL,
              mfe_r REAL, mae_r REAL, payload_json TEXT);
            CREATE TABLE candidate_episode_links(candidate_id TEXT PRIMARY KEY, episode_id TEXT);
            CREATE TABLE strategy_review_episode_links(candidate_id TEXT PRIMARY KEY,
              episode_id TEXT);
            CREATE TABLE broker_orders(decision_id TEXT PRIMARY KEY,
              realized_pnl_usd REAL);
            """
        )
        candidates = [
            ("C1", "OBJECTIVE_LEVEL_FAILED_AUCTION", "2026-01-02T00:00:00Z"),
            ("C2", "OBJECTIVE_LEVEL_FAILED_AUCTION", "2026-01-02T00:15:00Z"),
            ("C3", "OBJECTIVE_LEVEL_FAILED_AUCTION", "2026-01-03T00:00:00Z"),
            ("C4", "VWAP_RECLAIM_MEAN_REVERSION", "2026-01-04T00:00:00Z"),
        ]
        connection.executemany("INSERT INTO candidates VALUES (?,?,?)", candidates)
        for index, candidate_id in enumerate(("C1", "C2", "C3"), 1):
            connection.execute(
                "INSERT INTO agent_decisions VALUES (?,?,?,?)",
                (f"D{index}", candidate_id, "RULE_BASELINE", "2026-01-02T00:00:00Z"),
            )
            net = {-1: -0.1}.get(index, -0.1 if index < 3 else -0.2)
            connection.execute(
                "INSERT INTO decision_outcomes VALUES (?,?,?,?,?)",
                (
                    f"D{index}",
                    net,
                    1.2,
                    1.1,
                    json.dumps({"spread_pips": 1.0, "stop_pips": 4.0}),
                ),
            )
        connection.executemany(
            "INSERT INTO candidate_episode_links VALUES (?,?)",
            [("C1", "E1"), ("C2", "E1"), ("C3", "E2")],
        )
        connection.execute(
            "INSERT INTO agent_decisions VALUES (?,?,?,?)",
            ("D4", "C4", "LLM_STRATEGY_REVIEW_V2_SHADOW", "2026-01-04T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO decision_outcomes VALUES (?,?,?,?,?)",
            ("D4", 0.5, 1.5, 0.5, json.dumps({"spread_pips": 1.0, "stop_pips": 5.0})),
        )
        connection.execute(
            "INSERT INTO strategy_review_episode_links VALUES (?,?)", ("C4", "R1")
        )
        connection.commit()
        connection.close()

    def test_report_keeps_evidence_classes_separate_and_deduplicates_episodes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent_db = root / "agent.sqlite3"
            self._agent_db(agent_db)
            experiment = root / "experiment.json"
            experiment.write_text(
                json.dumps(
                    {
                        "experiment_epoch": "TEST_EPOCH",
                        "experiment_epoch_started_at_utc": "2026-01-01T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            validation = root / "validation.json"
            validation.write_text(
                json.dumps(
                    {
                        "profile_rows": [
                            {
                                "profile_id": "P1",
                                "family_id": "F1",
                                "direction": "LONG",
                                "profile_status": "PROFILE_READY_FOR_RUNTIME_ACCRUAL",
                                "research_evidence": {
                                    "unique_market_event_count": 50,
                                    "signal_avg_net_r_close": 0.1,
                                    "edge_vs_best_control_net_r": 0.2,
                                    "positive_month_rate": 0.7,
                                    "worst_month_avg_net_r": -0.1,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            dated = root / "dated.json"
            dated.write_text(
                json.dumps(
                    {
                        "profile_rows": [
                            {
                                "profile_id": "P1",
                                "exact_match_count": 0,
                                "ready_outcome_count": 0,
                                "dated_confirmation_state": "WAITING_FOR_EXACT_PROFILE_MATCH",
                                "metrics": {"avg_net_r": None},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = build_cross_system_edge_forensics(
                self.research,
                agent_db_path=agent_db,
                agent_experiment_contract_path=experiment,
                eur_profile_validation_path=validation,
                eur_profile_dated_path=dated,
            )
        self.assertEqual(report["pair_research"]["study_count"], 1)
        self.assertEqual(
            report["eur_agent_forward"]["rule_baseline_independent_episode_count"], 2
        )
        baseline = report["eur_agent_forward"]["rule_baseline_independent_episode_summary"]
        self.assertEqual(baseline["net_r"]["average"], -0.15)
        self.assertEqual(baseline["average_net_plus_entry_spread_r_proxy"], 0.1)
        self.assertEqual(
            report["eur_usd_historical_profiles"]["forward_ready_outcome_count"], 0
        )
        self.assertFalse(report["authority"]["automatic_strategy_changes"])


if __name__ == "__main__":
    unittest.main()
