import json
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fx_research_agent.asia_range_compression import _outcome, evaluate_rows
from fx_research_agent.campaigns import validate_campaign


CAMPAIGN_PATH = Path("config/campaigns/eur_asia_range_compression_london_breakout_v1.json")


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def synthetic_market(include_spread: bool = True):
    london = ZoneInfo("Europe/London")
    candles = []
    spreads = []
    current = date(2026, 9, 1)
    trading_days = []
    while len(trading_days) < 21:
        if current.weekday() < 5:
            trading_days.append(current)
        current += timedelta(days=1)
    for day_index, local_day in enumerate(trading_days):
        compressed = day_index == 20
        base = 1.1000
        range_half = 0.00025 if compressed else 0.00050
        local_start = datetime.combine(local_day, time(0, 0), tzinfo=london)
        for bar in range(56):
            start = local_start + timedelta(minutes=15 * bar)
            end = start + timedelta(minutes=15)
            open_ = base
            high = base + range_half
            low = base - range_half
            close = base
            if compressed and bar == 28:
                close = base + 0.00040
                high = close + 0.00002
            if compressed and bar >= 29:
                open_ = base + 0.00040
                close = open_
                high = open_ + 0.00020
                low = open_ - 0.00005
            if compressed and bar == 30:
                high = base + 0.00135
            candles.append({
                "instrument": "EUR_USD",
                "granularity": "M15",
                "candle_time_utc": iso(start),
                "candle_end_time_utc": iso(end),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100,
            })
        if compressed and include_spread:
            decision = local_start + timedelta(hours=7, minutes=15)
            spreads.append({
                "instrument": "EUR_USD",
                "sample_time_utc": iso(decision - timedelta(seconds=10)),
                "spread_pips": 1.0,
                "tradeable": 1,
                "pricing_status": "OK",
            })
    approval = datetime.combine(trading_days[-1], time(0, 0), tzinfo=london)
    evaluated = datetime.combine(trading_days[-1], time(23, 0), tzinfo=london)
    return candles, spreads, iso(approval), iso(evaluated)


class AsiaRangeCompressionTests(unittest.TestCase):
    def setUp(self):
        self.campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))

    def test_campaign_is_locked_and_inert(self):
        validate_campaign(self.campaign)
        self.assertEqual(self.campaign["hypothesis_id"], "HYP_AUTO_9A5D49EF224FC93E0908")
        self.assertEqual(self.campaign["exact_specification"]["compression_ratio_maximum"], 0.60)
        self.assertEqual(self.campaign["exact_specification"]["target_r"], 1.5)
        self.assertEqual(len(self.campaign["controls"]), 3)
        self.assertFalse(self.campaign["authority"]["order_authority"])

    def test_compressed_breakout_builds_paired_priced_event(self):
        candles, spreads, approval, evaluated = synthetic_market()
        result = evaluate_rows(
            candles,
            spreads,
            self.campaign,
            approval_time_utc=approval,
            evaluated_at_utc=evaluated,
        )
        self.assertEqual(result["summaries"]["TREATMENT"]["priced_episode_count"], 1)
        self.assertEqual(result["summaries"]["OPPOSITE_DIRECTION_SAME_EVENT"]["priced_episode_count"], 1)
        self.assertEqual(result["summaries"]["ONE_COMPLETED_M15_SHIFT_SAME_DIRECTION"]["priced_episode_count"], 1)
        self.assertGreater(result["summaries"]["TREATMENT"]["average_net_r"], 1.0)

    def test_missing_timestamp_valid_spread_rejects_trigger(self):
        candles, spreads, approval, evaluated = synthetic_market(include_spread=False)
        result = evaluate_rows(
            candles,
            spreads,
            self.campaign,
            approval_time_utc=approval,
            evaluated_at_utc=evaluated,
        )
        self.assertEqual(result["summaries"]["TREATMENT"]["priced_episode_count"], 0)
        self.assertEqual(result["exclusions"]["NO_TIMESTAMP_VALID_SPREAD"], 1)

    def test_short_outcome_reports_direction_correct_excursions(self):
        start = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)
        candles = []
        for index in range(16):
            candles.append({
                "candle_time_utc": iso(start + timedelta(minutes=15 * index)),
                "candle_end_time_utc": iso(start + timedelta(minutes=15 * (index + 1))),
                "open": 1.1000,
                "high": 1.1002,
                "low": 1.0996,
                "close": 1.1000,
            })
        outcome = _outcome(candles, 0, "SHORT", 0.0010, 1.5, 16, 1.0, 0.0001)
        self.assertIsNotNone(outcome)
        self.assertAlmostEqual(outcome["mfe_r"], 0.4)
        self.assertAlmostEqual(outcome["mae_r"], -0.2)


if __name__ == "__main__":
    unittest.main()
