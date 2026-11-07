import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from fx_research_agent.campaigns import validate_campaign
from fx_research_agent.futures_context_research import (
    _outcome,
    _trading_day,
    attach_futures_context,
    statistic_changes_before,
)


class FuturesContextResearchTests(unittest.TestCase):
    def test_campaign_is_locked_development_only_and_inert(self):
        campaign = json.loads(
            Path("config/campaigns/multipair_cme_futures_context_breakout_retest_v1.json").read_text(
                encoding="utf-8"
            )
        )
        validate_campaign(campaign)
        self.assertEqual(campaign["multiple_comparisons_policy"]["primary_hypothesis_count"], 3)
        self.assertFalse(campaign["multiple_comparisons_policy"]["parameter_sweeps_allowed"])
        self.assertEqual(campaign["population"]["validation_and_confirmation_rows_permitted_in_development"], 0)
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_new_york_1700_boundary_labels_next_trading_day(self):
        times = pd.Series(
            pd.to_datetime(["2026-07-01T20:59:00Z", "2026-07-01T21:00:00Z"], utc=True)
        )
        self.assertEqual(_trading_day(times).tolist(), ["2026-07-01", "2026-07-02"])

    def test_statistic_changes_are_strictly_past_only(self):
        decision = pd.Timestamp("2026-01-03T12:00:00Z")
        frame = pd.DataFrame(
            [
                {
                    "available_at_utc": pd.Timestamp("2026-01-01T12:00:00Z"),
                    "reference_time_utc": pd.Timestamp("2025-12-31T00:00:00Z"),
                    "normalized_stat_name": "OPEN_INTEREST",
                    "quantity": 100.0,
                    "normalized_price": None,
                },
                {
                    "available_at_utc": pd.Timestamp("2026-01-02T12:00:00Z"),
                    "reference_time_utc": pd.Timestamp("2026-01-01T00:00:00Z"),
                    "normalized_stat_name": "OPEN_INTEREST",
                    "quantity": 120.0,
                    "normalized_price": None,
                },
                {
                    "available_at_utc": decision,
                    "reference_time_utc": pd.Timestamp("2026-01-02T00:00:00Z"),
                    "normalized_stat_name": "OPEN_INTEREST",
                    "quantity": 999.0,
                    "normalized_price": None,
                },
            ]
        )
        result = statistic_changes_before(frame, [decision], "OPEN_INTEREST")[decision]
        self.assertEqual(result["current"], 120.0)
        self.assertEqual(result["change"], 20.0)

    def test_same_bar_tie_is_stop_first_and_cost_is_deducted(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = []
        for index in range(20):
            time = start + timedelta(minutes=15 * index)
            rows.append(
                {
                    "time": pd.Timestamp(time),
                    "end_time": pd.Timestamp(time + timedelta(minutes=15)),
                    "open": 1.0,
                    "high": 1.001,
                    "low": 0.999,
                    "close": 1.0,
                }
            )
        frame = pd.DataFrame(rows)
        result = _outcome(
            frame,
            1,
            "LONG",
            stop=0.999,
            target=1.0015,
            risk=0.001,
            horizon=16,
            cost_pips=1.5,
            pip_size=0.0001,
        )
        self.assertEqual(result["exit_reason"], "STOP")
        self.assertLess(result["net_r"], -1.0)

    def test_context_membership_requires_locked_thresholds(self):
        decision = pd.Timestamp("2026-01-03T12:00:00Z")
        event = {
            "instrument": "EUR_USD",
            "direction": "LONG",
            "decision_time": decision,
            "net_r": 1.0,
            "mfe_r": 1.5,
            "mae_r": -0.2,
        }
        futures = pd.DataFrame(
            [{"end_time": decision, "return": 0.001, "volume_ratio": 1.3}]
        ).set_index("end_time", drop=False)
        statistics = pd.DataFrame(
            [
                {"available_at_utc": pd.Timestamp("2026-01-01T10:00:00Z"), "reference_time_utc": pd.Timestamp("2025-12-31T00:00:00Z"), "normalized_stat_name": "OPEN_INTEREST", "quantity": 100.0, "normalized_price": None},
                {"available_at_utc": pd.Timestamp("2026-01-02T10:00:00Z"), "reference_time_utc": pd.Timestamp("2026-01-01T00:00:00Z"), "normalized_stat_name": "OPEN_INTEREST", "quantity": 110.0, "normalized_price": None},
                {"available_at_utc": pd.Timestamp("2026-01-01T11:00:00Z"), "reference_time_utc": pd.Timestamp("2025-12-31T00:00:00Z"), "normalized_stat_name": "SETTLEMENT_PRICE", "quantity": None, "normalized_price": 1.0},
                {"available_at_utc": pd.Timestamp("2026-01-02T11:00:00Z"), "reference_time_utc": pd.Timestamp("2026-01-01T00:00:00Z"), "normalized_stat_name": "SETTLEMENT_PRICE", "quantity": None, "normalized_price": 1.01},
            ]
        )
        result = attach_futures_context([event], futures, statistics)[0]
        self.assertTrue(result["treatment_membership"]["INTRADAY_VOLUME_CONFIRMATION"])
        self.assertTrue(result["treatment_membership"]["OI_AND_SETTLEMENT_CONFIRMATION"])
        self.assertTrue(result["treatment_membership"]["ALL_CONTEXT_CONFLUENCE"])


if __name__ == "__main__":
    unittest.main()
