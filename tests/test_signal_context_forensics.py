import unittest

from fx_research_agent.signal_context_forensics import (
    _candidate_strategy_facts,
    _direction_alignment,
    build_signal_context_forensics,
    build_strategy_context_report,
)


class SignalContextForensicsTests(unittest.TestCase):
    def test_regime_direction_alignment_is_relative_to_signal(self):
        self.assertEqual(_direction_alignment("UP", "LONG"), "ALIGNED")
        self.assertEqual(_direction_alignment("DOWN", "SHORT"), "ALIGNED")
        self.assertEqual(_direction_alignment("UP", "SHORT"), "OPPOSED")
        self.assertEqual(_direction_alignment("FLAT", "LONG"), "FLAT")

    def test_original_candidates_keep_outcome_source_and_context(self):
        candidates = [
            {
                "candidate_id": "C1",
                "instrument": "EUR_USD",
                "mechanism_class": "OBJECTIVE_LEVEL_FAILED_AUCTION",
                "level_signature": "PRIOR_DAY_HIGH",
                "direction": "SHORT",
                "decision_time_utc": "2026-11-01T10:00:00Z",
                "market_facts": {
                    "session_bucket": "LONDON",
                    "atr_pips": 10.0,
                    "spread_pips": 1.0,
                    "htf_alignment": "ALIGNED",
                },
                "objective_levels": [{"touch_index": 3}],
            }
        ]
        outcomes = [
            {
                "outcome_id": "O1",
                "candidate_id": "C1",
                "arm_id": "RULE_BASELINE",
                "outcome_source": "FORWARD_ABSTENTION_COUNTERFACTUAL",
                "entry_model": "NEXT_M15_OPEN",
                "horizon_bars": 4,
                "target_r": 1.5,
                "same_bar_tie_policy": "STOP_FIRST",
                "realized_net_r": 1.5,
            }
        ]
        events, translated = _candidate_strategy_facts(candidates, outcomes)
        report = build_strategy_context_report(
            events, translated, minimum_slice_count=1
        )
        self.assertEqual(report["independent_outcome_count"], 1)
        self.assertEqual(report["signal_count"], 1)
        self.assertIn(
            "FORWARD_ABSTENTION_COUNTERFACTUAL",
            report["signal_summaries"][0]["signal_id"],
        )
        self.assertEqual(
            report["context_coverage_counts"]["maximum_touch_index"], 1
        )

    def test_report_deduplicates_horizons_and_corrects_all_slice_tests(self):
        events = []
        outcomes = []
        for mechanism_index, mechanism in enumerate(("SIGNAL_A", "SIGNAL_B")):
            for index in range(20):
                event_id = f"{mechanism}_{index}"
                session = "LONDON" if index < 10 else "NY_AFTERNOON"
                events.append(
                    {
                        "event_id": event_id,
                        "instrument": "EUR_USD",
                        "mechanism_id": mechanism,
                        "setup_id": "SETUP",
                        "direction": "SHORT",
                        "decision_time_utc": f"2026-01-{index + 1:02d}T08:00:00Z",
                        "feature_packet": {
                            "session_bucket": session,
                            "markov_state": "LONDON|DOWN|EXPANDING",
                            "hmm_state": "NOT_CONNECTED",
                            "garch_volatility_state": "LOW",
                            "h1_trend_state": "DOWN",
                            "h4_trend_state": "DOWN",
                            "atr_pips": 4.0,
                            "spread_pips": 1.5,
                            "candle": {
                                "open": 1.1,
                                "high": 1.1004,
                                "low": 1.0997,
                                "close": 1.0998,
                            },
                        },
                    }
                )
                outcomes.append(
                    {
                        "event_id": event_id,
                        "realized_net_r": 1.5 if session == "LONDON" else -1.0,
                        "entry_model": "NEXT_OPEN",
                        "horizon_bars": 4,
                        "target_r": 1.5,
                        "same_bar_tie_policy": "STOP_FIRST",
                        "mfe_r": 1.5 if session == "LONDON" else 0.25,
                        "mae_r": 0.2 if session == "LONDON" else 1.0,
                        "exit_reason": "TARGET" if session == "LONDON" else "STOP",
                        "spread_pips": 1.0,
                        "stop_pips": 5.0,
                    }
                )
        report = build_strategy_context_report(events, outcomes)
        self.assertEqual(report["independent_outcome_count"], 40)
        self.assertEqual(report["signal_count"], 2)
        self.assertGreater(report["tested_slice_count"], 0)
        self.assertTrue(
            all(row["fdr_q_value"] >= row["p_value"] for row in report["context_slices"])
        )
        self.assertNotIn("hmm_state", report["context_coverage_counts"])
        london = [
            row
            for row in report["context_slices"]
            if row["dimension"] == "session_bucket" and row["value"] == "LONDON"
        ]
        self.assertEqual(len(london), 2)
        self.assertTrue(all(row["average_net_r_lift"] == 2.5 for row in london))
        self.assertTrue(report["pooled_within_signal_context"])
        paths = report["outcome_path_summary"]
        self.assertEqual(paths["positive"]["count"], 20)
        self.assertEqual(paths["non_positive"]["count"], 20)
        self.assertEqual(paths["positive"]["mfe_at_least_1_5r_rate"], 1.0)
        self.assertEqual(paths["non_positive"]["mae_at_least_1r_rate"], 1.0)

    def test_overlapping_events_are_not_counted_twice(self):
        events = []
        outcomes = []
        for index, hour in enumerate((8, 9, 13)):
            event_id = f"E{index}"
            events.append(
                {
                    "event_id": event_id,
                    "instrument": "EUR_USD",
                    "mechanism_id": "SIGNAL_A",
                    "setup_id": "SETUP",
                    "direction": "LONG",
                    "decision_time_utc": f"2026-01-02T{hour:02d}:00:00Z",
                    "feature_packet": {"session_bucket": "LONDON"},
                }
            )
            outcomes.append(
                {
                    "event_id": event_id,
                    "realized_net_r": 1.0,
                    "entry_model": "NEXT_OPEN",
                    "horizon_bars": 16,
                    "target_r": 1.0,
                    "same_bar_tie_policy": "STOP_FIRST",
                }
            )
        report = build_strategy_context_report(events, outcomes, minimum_slice_count=1)
        self.assertEqual(report["independent_outcome_count"], 2)

    def test_report_builder_filters_strategy_events_to_requested_instrument(self):
        class Connection:
            pass

        import unittest.mock

        evidence = {
            "manifest_ids": [],
            "strategy_events": {
                "EUR": {
                    "event_id": "EUR",
                    "instrument": "EUR_USD",
                    "mechanism_id": "M",
                    "setup_id": "S",
                    "direction": "LONG",
                    "decision_time_utc": "2026-01-01T00:00:00Z",
                    "feature_packet": {},
                },
                "AUD": {
                    "event_id": "AUD",
                    "instrument": "AUD_USD",
                    "mechanism_id": "M",
                    "setup_id": "S",
                    "direction": "LONG",
                    "decision_time_utc": "2026-01-01T00:00:00Z",
                    "feature_packet": {},
                },
            },
            "strategy_outcomes": {
                key: {
                    "event_id": key,
                    "realized_net_r": 1.0,
                    "entry_model": "NEXT_OPEN",
                    "horizon_bars": 4,
                    "target_r": 1.5,
                    "same_bar_tie_policy": "STOP_FIRST",
                }
                for key in ("EUR", "AUD")
            },
            "candidates": {},
            "outcomes": {},
        }
        with unittest.mock.patch(
            "fx_research_agent.signal_context_forensics._load_evidence",
            return_value=evidence,
        ):
            result = build_signal_context_forensics(
                Connection(), None, instrument="EUR_USD"
            )
        self.assertEqual(result["strategy_shadow"]["independent_outcome_count"], 1)


if __name__ == "__main__":
    unittest.main()
