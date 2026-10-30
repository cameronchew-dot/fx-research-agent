import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_research_agent.campaigns import validate_campaign
from fx_research_agent.cftc_tff_positioning import (
    _direction,
    _first_candle_after,
    _outcome,
    build_extreme_episodes,
    load_reports,
)


class CftcTffPositioningTests(unittest.TestCase):
    def test_locked_campaign_is_valid_and_inert(self):
        campaign = json.loads(
            Path("config/campaigns/cftc_tff_fx_crowding_reversal_v1.json").read_text(encoding="utf-8")
        )
        validate_campaign(campaign)
        self.assertFalse(campaign["authority"]["order_authority"])
        self.assertEqual(campaign["population"]["validation_and_holdout_rows_permitted_in_development"], 0)
        self.assertFalse(campaign["multiple_comparisons_policy"]["parameter_sweeps_allowed"])

    def test_report_loader_rejects_duplicate_ids_per_instrument_date(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reports.csv.gz"
            fields = ["report_id", "report_date", "instrument", "leveraged_money_net_share"]
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                import csv

                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"report_id": "1", "report_date": "2020-01-07", "instrument": "EUR_USD", "leveraged_money_net_share": "0.1"})
                writer.writerow({"report_id": "2", "report_date": "2020-01-07", "instrument": "EUR_USD", "leveraged_money_net_share": "0.2"})
            with self.assertRaisesRegex(ValueError, "duplicate CFTC report"):
                load_reports(path)

    def test_z_score_uses_prior_reports_only_and_rearms(self):
        start = datetime(2010, 1, 5, tzinfo=timezone.utc)
        reports = []
        for index in range(104):
            reports.append(
                {
                    "report_id": str(index),
                    "report_date": (start + timedelta(days=7 * index)).date().isoformat(),
                    "report_time": start + timedelta(days=7 * index),
                    "net_share": -0.1 if index % 2 else 0.1,
                }
            )
        reports.extend(
            [
                {"report_id": "extreme-1", "report_date": "2012-01-10", "report_time": start + timedelta(days=7 * 104), "net_share": 0.5},
                {"report_id": "same-tail", "report_date": "2012-01-17", "report_time": start + timedelta(days=7 * 105), "net_share": 0.5},
                {"report_id": "rearm", "report_date": "2012-01-24", "report_time": start + timedelta(days=7 * 106), "net_share": 0.0},
                {"report_id": "extreme-2", "report_date": "2012-01-31", "report_time": start + timedelta(days=7 * 107), "net_share": -0.5},
            ]
        )
        episodes = build_extreme_episodes(
            reports,
            lookback=156,
            minimum_history=104,
            extreme_z=1.5,
            rearm_z=1.0,
            development_end=datetime(2017, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual([row["report_id"] for row in episodes], ["extreme-1", "extreme-2"])
        self.assertGreater(episodes[0]["z_score"], 1.5)
        self.assertLess(episodes[1]["z_score"], -1.5)

    def test_entry_search_is_strictly_after_availability(self):
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        candles = [{"time": start + timedelta(days=index)} for index in range(5)]
        self.assertEqual(_first_candle_after(candles, start + timedelta(days=2)), 3)

    def test_direction_mapping_fades_foreign_currency_crowding(self):
        self.assertEqual(_direction("EUR_USD", 1), "SHORT")
        self.assertEqual(_direction("AUD_USD", -1), "LONG")
        self.assertEqual(_direction("USD_JPY", 1), "LONG")
        self.assertEqual(_direction("USD_JPY", -1), "SHORT")

    def test_same_bar_tie_is_stop_first_and_cost_is_deducted(self):
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        candles = []
        for index in range(45):
            row = {
                "time": start + timedelta(days=index),
                "candle_time_utc": (start + timedelta(days=index)).isoformat().replace("+00:00", "Z"),
                "candle_end_time_utc": (start + timedelta(days=index + 1)).isoformat().replace("+00:00", "Z"),
                "open": 1.0,
                "high": 1.001,
                "low": 0.999,
                "close": 1.0,
            }
            candles.append(row)
        # The entry bar reaches both a 2 ATR stop and 3 ATR target.
        candles[21].update({"high": 1.006, "low": 0.996})
        result = _outcome(
            candles,
            21,
            "LONG",
            atr_period=20,
            stop_atr=2.0,
            target_atr=3.0,
            horizon=20,
            cost_pips=2.0,
            pip_size=0.0001,
            development_end=datetime(2021, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result["exit_reason"], "STOP")
        self.assertLess(result["net_r"], -1.0)


if __name__ == "__main__":
    unittest.main()
