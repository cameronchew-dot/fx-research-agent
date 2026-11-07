import json
import unittest
from pathlib import Path

import pandas as pd

from fx_research_agent.campaigns import validate_campaign
from fx_research_agent.futures_participation_shock import (
    ACCEPTANCE,
    REVERSAL,
    classify_participation_shock,
)


def shock_row(*, open_: float, high: float, low: float, close: float, volume_ratio: float = 2.0, range_ratio: float = 2.0):
    return pd.Series(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume_ratio": volume_ratio,
            "range_ratio": range_ratio,
            "source_minutes": 15,
        }
    )


class FuturesParticipationShockTests(unittest.TestCase):
    def test_campaign_is_two_hypothesis_development_only_and_inert(self):
        campaign = json.loads(
            Path("config/campaigns/multipair_cme_participation_shock_v1.json").read_text(encoding="utf-8")
        )
        validate_campaign(campaign)
        self.assertEqual(campaign["multiple_comparisons_policy"]["primary_hypothesis_count"], 2)
        self.assertFalse(campaign["multiple_comparisons_policy"]["parameter_sweeps_allowed"])
        self.assertEqual(campaign["population"]["validation_and_confirmation_rows_permitted_in_development"], 0)
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_acceptance_continuation_classification(self):
        self.assertEqual(
            classify_participation_shock(
                shock_row(open_=100.0, high=103.0, low=99.5, close=102.8),
                100.0,
            ),
            (ACCEPTANCE, "LONG"),
        )
        self.assertEqual(
            classify_participation_shock(
                shock_row(open_=100.0, high=100.5, low=97.0, close=97.2),
                100.0,
            ),
            (ACCEPTANCE, "SHORT"),
        )

    def test_failed_auction_reversal_classification(self):
        self.assertEqual(
            classify_participation_shock(
                shock_row(open_=100.0, high=103.0, low=99.5, close=100.0),
                100.0,
            ),
            (REVERSAL, "SHORT"),
        )
        self.assertEqual(
            classify_participation_shock(
                shock_row(open_=100.0, high=100.5, low=97.0, close=100.0),
                100.0,
            ),
            (REVERSAL, "LONG"),
        )

    def test_subthreshold_volume_or_range_is_not_an_event(self):
        self.assertIsNone(
            classify_participation_shock(
                shock_row(open_=100.0, high=103.0, low=99.5, close=102.8, volume_ratio=1.74),
                100.0,
            )
        )

    def test_evaluator_shape_keeps_end_time_index_and_column_intentionally(self):
        # The evaluator sorts by the time index because end_time is retained as
        # both the lookup index and an auditable value column.
        frame = pd.DataFrame(
            [{"end_time": pd.Timestamp("2026-01-01T00:15:00Z"), "close": 1.0}]
        ).set_index("end_time", drop=False)
        sorted_frame = frame.sort_index()
        self.assertEqual(sorted_frame.iloc[0]["close"], 1.0)
        self.assertIsNone(
            classify_participation_shock(
                shock_row(open_=100.0, high=103.0, low=99.5, close=102.8, range_ratio=1.49),
                100.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
