import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fx_research_agent.alpaca_intraday import (
    build_session_rows,
    evaluate,
    newey_west_t_stat,
    normalize_bar,
    summarize,
)


NEW_YORK = ZoneInfo("America/New_York")


def minute(day, clock, *, open_price, close_price):
    local = datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=NEW_YORK)
    return {
        "timestamp_utc": local.astimezone(ZoneInfo("UTC")),
        "open": float(open_price),
        "high": float(max(open_price, close_price)),
        "low": float(min(open_price, close_price)),
        "close": float(close_price),
    }


def synthetic_minutes():
    specifications = {
        "2026-11-02": {"morning": 100, "entry": 100, "exit": 100, "close": 100},
        "2026-11-03": {"morning": 101, "entry": 100, "exit": 101, "close": 101},
        "2026-11-04": {"morning": 100, "entry": 100, "exit": 99, "close": 99},
        "2026-11-05": {"morning": 100, "entry": 100, "exit": 101, "close": 101},
    }
    rows = []
    for day, values in specifications.items():
        rows.extend(
            [
                minute(day, "09:30", open_price=values["morning"], close_price=values["morning"]),
                minute(day, "09:59", open_price=values["morning"], close_price=values["morning"]),
                minute(day, "15:30", open_price=values["entry"], close_price=values["entry"]),
                minute(day, "15:55", open_price=values["exit"], close_price=values["exit"]),
                minute(day, "15:59", open_price=values["close"], close_price=values["close"]),
            ]
        )
    return sorted(rows, key=lambda row: row["timestamp_utc"])


class AlpacaIntradayTests(unittest.TestCase):
    def test_qqq_gap_campaign_is_frozen_and_inert(self):
        campaign = json.loads(
            Path("config/campaigns/qqq_overnight_gap_first_half_hour_reversal_v1.json").read_text()
        )
        exact = campaign["exact_specification"]
        self.assertEqual(campaign["instrument"], "QQQ")
        self.assertEqual(exact["entry"], "CURRENT_SESSION_09_31_MINUTE_OPEN")
        self.assertEqual(exact["exit"], "CURRENT_SESSION_09_59_MINUTE_CLOSE")
        self.assertFalse(exact["parameter_sweeps_allowed"])
        self.assertFalse(exact["gap_threshold_sweeps_allowed"])
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_normalize_bar_supports_an_explicit_symbol(self):
        row = normalize_bar(
            {
                "t": "2026-11-03T14:30:00Z",
                "o": 100,
                "h": 101,
                "l": 99,
                "c": 100.5,
                "v": 10,
                "n": 2,
                "vw": 100.25,
            },
            symbol="QQQ",
        )
        self.assertEqual(row["symbol"], "QQQ")

    def test_sector_campaign_is_frozen_inert_and_frequency_targeted(self):
        campaign = json.loads(
            Path("config/campaigns/sector_etf_cross_sectional_overnight_reversal_v1.json").read_text()
        )
        exact = campaign["exact_specification"]
        self.assertEqual(len(campaign["population"]["sector_universe"]), 9)
        self.assertEqual(exact["entry"], "CURRENT_SESSION_09_45_BAR_OPEN")
        self.assertEqual(exact["exit"], "CURRENT_SESSION_10_15_BAR_CLOSE")
        self.assertFalse(exact["parameter_sweeps_allowed"])
        self.assertEqual(
            campaign["multiple_comparisons_policy"]["holm_first_order_two_sided_t_threshold"],
            2.24,
        )
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_campaign_is_frozen_and_inert(self):
        campaign = json.loads(
            Path("config/campaigns/spy_morning_momentum_last_half_hour_v1.json").read_text()
        )
        self.assertFalse(campaign["exact_specification"]["parameter_sweeps_allowed"])
        self.assertEqual(campaign["exact_specification"]["exit"], "CURRENT_SESSION_15_55_MINUTE_OPEN")
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_normalize_bar_rejects_invalid_ohlc(self):
        with self.assertRaisesRegex(ValueError, "OHLC"):
            normalize_bar(
                {
                    "t": "2026-11-03T14:30:00Z",
                    "o": 100,
                    "h": 99,
                    "l": 98,
                    "c": 100,
                    "v": 1,
                    "n": 1,
                    "vw": 100,
                }
            )

    def test_session_signal_and_prior_day_control_are_causal(self):
        rows = build_session_rows(
            synthetic_minutes(), start_date="2026-11-01", end_date="2026-11-06"
        )
        self.assertEqual([row["date"] for row in rows], ["2026-11-03", "2026-11-04", "2026-11-05"])
        self.assertTrue(rows[0]["primary_active"])
        self.assertFalse(rows[0]["prior_day_active"])
        self.assertFalse(rows[1]["primary_active"])
        self.assertTrue(rows[1]["prior_day_active"])
        self.assertTrue(rows[2]["primary_active"])
        self.assertFalse(rows[2]["prior_day_active"])
        metrics = summarize(rows, "primary", 0.0)
        self.assertEqual(metrics["trade_count"], 2)
        self.assertAlmostEqual(metrics["average_net_return_per_trade"], 0.01)

    def test_newey_west_t_stat_has_expected_direction(self):
        positive = [0.005 + (index % 3) * 0.001 for index in range(20)]
        self.assertGreater(newey_west_t_stat(positive), 0)
        self.assertLess(newey_west_t_stat([-value for value in positive]), 0)

    def test_evaluation_is_deterministic_and_never_promotable(self):
        campaign = json.loads(
            Path("config/campaigns/spy_morning_momentum_last_half_hour_v1.json").read_text()
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                fields = ["timestamp_utc", "symbol", "open", "high", "low", "close"]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for row in synthetic_minutes():
                    writer.writerow(
                        {
                            "timestamp_utc": row["timestamp_utc"].isoformat().replace("+00:00", "Z"),
                            "symbol": "SPY",
                            "open": row["open"],
                            "high": row["high"],
                            "low": row["low"],
                            "close": row["close"],
                        }
                    )
            first = evaluate(path, campaign)
            second = evaluate(path, campaign)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "HISTORICAL_GATE_FAIL")
        self.assertFalse(first["promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
