import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.storage import initialize
from fx_research_agent.strategy_coverage import build_strategy_coverage


class StrategyCoverageTests(unittest.TestCase):
    def test_report_maps_families_without_changing_authority(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        initialize(connection)
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "config").mkdir()
                (root / "data").mkdir()
                (root / "config" / "eur_family_plugins.json").write_text(
                    json.dumps(
                        {
                            "families": [
                                {
                                    "id": "VWAP_RECLAIM",
                                    "display_name": "VWAP Reclaim",
                                    "generator": {"status": "IMPLEMENTED_RESEARCH_ONLY"},
                                    "lifecycle": {"stage": "RESEARCH"},
                                },
                                {
                                    "id": "UNMAPPED",
                                    "display_name": "Unmapped",
                                    "generator": {"status": "RESEARCH_ONLY"},
                                    "lifecycle": {"stage": "RESEARCH"},
                                },
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                (root / "data" / "eur_family_validation.json").write_text(
                    json.dumps(
                        {
                            "summary": {"paper_candidate_metric_pass_count": 0},
                            "evaluations": [
                                {
                                    "family_id": "VWAP_RECLAIM",
                                    "validation_decision": "FAIL_EVIDENCE_VALIDATION",
                                    "metrics": {
                                        "count": 100,
                                        "avg_net_r_close": -0.1,
                                        "positive_close_rate": 0.4,
                                    },
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                (root / "data" / "eur_lifecycle_registry.json").write_text(
                    json.dumps({"active_profile_candidate_auto_queue": []}),
                    encoding="utf-8",
                )
                (root / "data" / "eur_portfolio_integrity.json").write_text(
                    json.dumps(
                        {
                            "portfolio_integrity_status": "PARTIAL",
                            "exact_historical_profile_cadence": {
                                "selector_realistic_metrics": {
                                    "avg_events_per_week": 0.12
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                (root / "config" / "eur_oanda_practice_execution_contract.json").write_text(
                    json.dumps(
                        {
                            "venue": "OANDA_PRACTICE",
                            "reference_account_model": {
                                "reference_equity_usd": 1000.0,
                                "risk_per_trade_fraction": 0.005,
                                "broker_account_balance_used_for_sizing": False,
                                "max_open_managed_trades": 1,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                contract = root / "coverage.json"
                contract.write_text(
                    json.dumps(
                        {
                            "schema": "TEST",
                            "groups": [
                                {
                                    "group_id": "MEAN_REVERSION",
                                    "family_ids": ["VWAP_RECLAIM"],
                                    "campaign_ids": [],
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

                report = build_strategy_coverage(
                    connection,
                    eur_bot_root=root,
                    contract_path=contract,
                    generated_at_utc="2026-11-19T00:00:00Z",
                )

            self.assertEqual(report["summary"]["covered_family_count"], 1)
            self.assertEqual(report["summary"]["exact_historical_avg_trades_per_week"], 0.12)
            self.assertEqual(report["unmapped_family_ids"], ["UNMAPPED"])
            self.assertTrue(report["safety"]["reporting_only"])
            self.assertFalse(report["safety"]["orders_submitted"])
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
