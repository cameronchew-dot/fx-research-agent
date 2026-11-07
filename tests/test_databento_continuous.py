import unittest
from datetime import date

import pandas as pd

from fx_research_agent.databento_continuous import (
    build_roll_schedule,
    cme_session_date,
    excluded_session_dates,
    normalize_ohlc,
)


class DatabentoContinuousTests(unittest.TestCase):
    def test_six_j_ohlc_inversion_swaps_high_and_low(self) -> None:
        normalized = normalize_ohlc("6J", 0.0065, 0.0066, 0.0064, 0.00655)
        self.assertAlmostEqual(normalized[0], 1 / 0.0065)
        self.assertAlmostEqual(normalized[1], 1 / 0.0064)
        self.assertAlmostEqual(normalized[2], 1 / 0.0066)
        self.assertAlmostEqual(normalized[3], 1 / 0.00655)

    def test_session_date_uses_cme_chicago_17_hour_boundary(self) -> None:
        self.assertEqual(cme_session_date(pd.Timestamp("2026-07-06T21:59:00Z")), date(2026, 7, 6))
        self.assertEqual(cme_session_date(pd.Timestamp("2026-07-06T22:01:00Z")), date(2026, 7, 7))

    def test_degraded_utc_date_excludes_every_intersecting_session(self) -> None:
        sessions = excluded_session_dates(["2026-07-06"])
        self.assertIn(date(2026, 7, 6), sessions)
        self.assertIn(date(2026, 7, 7), sessions)

    def test_next_session_uses_only_previous_session_volume(self) -> None:
        rows = [
            {"session_date": date(2026, 1, 5), "symbol": "6EH6", "volume": 100, "last_close": 1.10, "expiration_utc": "2026-03-16T00:00:00Z"},
            {"session_date": date(2026, 1, 5), "symbol": "6EM6", "volume": 50, "last_close": 1.11, "expiration_utc": "2026-06-15T00:00:00Z"},
            {"session_date": date(2026, 1, 6), "symbol": "6EH6", "volume": 1, "last_close": 1.12, "expiration_utc": "2026-03-16T00:00:00Z"},
            {"session_date": date(2026, 1, 6), "symbol": "6EM6", "volume": 1000, "last_close": 1.13, "expiration_utc": "2026-06-15T00:00:00Z"},
            {"session_date": date(2026, 1, 7), "symbol": "6EH6", "volume": 2, "last_close": 1.14, "expiration_utc": "2026-03-16T00:00:00Z"},
            {"session_date": date(2026, 1, 7), "symbol": "6EM6", "volume": 900, "last_close": 1.15, "expiration_utc": "2026-06-15T00:00:00Z"},
        ]
        schedule = build_roll_schedule(pd.DataFrame(rows), "6E").set_index("session_date")
        self.assertEqual(schedule.loc[date(2026, 1, 6), "selected_symbol"], "6EH6")
        self.assertEqual(schedule.loc[date(2026, 1, 7), "selected_symbol"], "6EM6")
        self.assertEqual(
            schedule.loc[date(2026, 1, 7), "adjustment_status"],
            "CAUSAL_PRIOR_SESSION_RATIO_ROLL",
        )
        self.assertAlmostEqual(
            schedule.loc[date(2026, 1, 7), "adjustment_factor"], 1.12 / 1.13
        )


if __name__ == "__main__":
    unittest.main()

