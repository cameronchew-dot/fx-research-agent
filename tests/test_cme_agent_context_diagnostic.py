import unittest
from datetime import timedelta

import numpy as np
import pandas as pd

from fx_research_agent.cme_agent_context_diagnostic import (
    build_futures_features,
    fit_logistic_predict,
    join_cme_features,
    roc_auc,
)


class _Dataset:
    def __init__(self, frame):
        self.frame = frame


class CmeAgentContextTests(unittest.TestCase):
    def test_auc_handles_ties(self):
        self.assertEqual(roc_auc([0, 1, 0, 1], [0.1, 0.9, 0.2, 0.8]), 1.0)
        self.assertEqual(roc_auc([0, 1], [0.5, 0.5]), 0.5)

    def test_logistic_learns_fixed_signal(self):
        rows = [
            {"x": float(value), "positive_label": int(value > 0)}
            for value in (-3, -2, -1, 1, 2, 3)
        ]
        probabilities = fit_logistic_predict(rows, [{"x": -2.0}, {"x": 2.0}], ("x",))
        self.assertLess(probabilities[0], 0.5)
        self.assertGreater(probabilities[1], 0.5)

    def test_join_uses_exact_complete_bar_and_direction(self):
        decision = pd.Timestamp("2026-10-08T17:30:00Z")
        frame = pd.DataFrame(
            [
                {
                    "return_15m_bps": 2.0,
                    "close_location": 0.5,
                    "return_60m_bps": 4.0,
                    "volume_ratio": 2.0,
                    "range_ratio": 1.5,
                    "volatility_ratio": 1.25,
                }
            ],
            index=pd.DatetimeIndex([decision]),
        )
        episodes = [
            {
                "candidate_id": "C1",
                "episode_id": "E1",
                "decision_time_utc": "2026-10-08T17:30:00Z",
                "direction": "SHORT",
                "realized_net_r": 1.0,
                "positive_label": 1,
            }
        ]
        joined = join_cme_features(episodes, frame)
        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0]["cme_directional_return_15m_bps"], -2.0)
        self.assertEqual(joined[0]["cme_directional_close_location"], -0.5)


if __name__ == "__main__":
    unittest.main()
