import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fx_research_agent.qqq_gap_reversal import (
    build_session_rows,
    evaluate,
    newey_west_t_stat,
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
        "2026-11-02": {"open": 100, "entry": 100, "exit": 100, "close": 100},
        "2026-11-03": {"open": 99, "entry": 99, "exit": 100, "close": 100},
        "2026-11-04": {"open": 101, "entry": 101, "exit": 100, "close": 100},
        "2026-11-05": {"open": 99, "entry": 99, "exit": 100, "close": 100},
    }
    rows = []
    for day, values in specifications.items():
        rows.extend(
            [
                minute(day, "09:30", open_price=values["open"], close_price=values["open"]),
                minute(day, "09:31", open_price=values["entry"], close_price=values["entry"]),
                minute(day, "09:59", open_price=values["exit"], close_price=values["exit"]),
                minute(day, "15:59", open_price=values["close"], close_price=values["close"]),
            ]
        )
    return sorted(rows, key=lambda row: row["timestamp_utc"])


class QqqGapReversalTests(unittest.TestCase):
    def test_campaign_is_frozen_and_inert(self):
        campaign = json.loads(
            Path("config/campaigns/qqq_overnight_gap_first_half_hour_reversal_v1.json").read_text()
        )
        self.assertEqual(campaign["instrument"], "QQQ")
        self.assertFalse(campaign["exact_specification"]["parameter_sweeps_allowed"])
        self.assertFalse(campaign["exact_specification"]["holding_period_sweeps_allowed"])
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_signal_timing_and_lagged_control_are_causal(self):
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
        self.assertGreater(metrics["average_net_return_per_trade"], 0.01)

    def test_newey_west_t_stat_has_expected_direction(self):
        positive = [0.005 + (index % 3) * 0.001 for index in range(20)]
        self.assertGreater(newey_west_t_stat(positive), 0)
        self.assertLess(newey_west_t_stat([-value for value in positive]), 0)

    def test_evaluation_is_deterministic_and_never_promotable(self):
        campaign = json.loads(
            Path("config/campaigns/qqq_overnight_gap_first_half_hour_reversal_v1.json").read_text()
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
                            "symbol": "QQQ",
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
        self.assertFalse(first["llm_selector_eligible"])

    def test_sealed_result_failed_without_llm_or_order_authority(self):
        result = json.loads(
            Path("data/results/qqq_overnight_gap_first_half_hour_reversal_v1.json").read_text()
        )
        self.assertEqual(result["status"], "HISTORICAL_GATE_FAIL")
        self.assertFalse(result["all_cost_scenarios_passed"])
        self.assertFalse(result["promotion_eligible"])
        self.assertFalse(result["llm_selector_eligible"])
        self.assertFalse(result["authority"]["order_authority"])
        self.assertEqual(
            result["provenance"]["bars_sha256"],
            "7e18dad3df89b1e2607740e2b43fafc1d76ce7b001aec972929a6d5225625a06",
        )
        combined = result["cost_scenarios"]["primary"]["validation_plus_dated"]["primary"]
        self.assertEqual(combined["trade_count"], 552)
        self.assertLess(combined["average_net_return_per_trade"], 0.0)


if __name__ == "__main__":
    unittest.main()
