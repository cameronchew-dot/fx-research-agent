from __future__ import annotations

import unittest

import pandas as pd

from fx_research_agent.cme_forward_context import build_snapshot


class CmeForwardContextTests(unittest.TestCase):
    def test_snapshot_uses_prior_baseline_and_complete_bars(self):
        times = pd.date_range("2026-01-01T00:00:00Z", periods=21 * 15, freq="min")
        minute = pd.Series(range(len(times)), dtype=float)
        frame = pd.DataFrame(
            {
                "event_time_utc": times,
                "adjusted_open": 1.0 + minute * 0.00001,
                "adjusted_high": 1.0002 + minute * 0.00001,
                "adjusted_low": 0.9998 + minute * 0.00001,
                "adjusted_close": 1.0001 + minute * 0.00001,
                "volume": [10] * (20 * 15) + [20] * 15,
            }
        )
        item = build_snapshot(frame, product="6E", build_id="BUILD")
        self.assertEqual(item["instrument"], "EUR_USD")
        self.assertEqual(item["bar_end_utc"], "2026-01-01T05:15:00Z")
        self.assertAlmostEqual(item["features"]["volume_ratio"], 2.0)
        self.assertEqual(item["features"]["source_minutes"], 15)
        self.assertFalse(item.get("execution_authority", False))


if __name__ == "__main__":
    unittest.main()
