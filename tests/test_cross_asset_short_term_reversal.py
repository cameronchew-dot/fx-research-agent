import csv
import gzip
import json
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fx_research_agent.campaigns import load_campaign
from fx_research_agent.cross_asset_short_term_reversal import (
    ALL_SYMBOLS,
    RISKY_SYMBOLS,
    _fixed_random_symbol,
    build_events,
    evaluate,
    load_daily_panel,
)


class CrossAssetShortTermReversalTests(unittest.TestCase):
    def _write_prices(self, path: Path, observations: int = 900) -> None:
        current = date(2015, 10, 1)
        rows = []
        index = 0
        prices = {symbol: 100.0 + offset * 10.0 for offset, symbol in enumerate(ALL_SYMBOLS)}
        while index < observations:
            if current.weekday() < 5:
                for offset, symbol in enumerate(ALL_SYMBOLS):
                    previous = prices[symbol]
                    wave = math.sin(index / (9.0 + offset)) * 0.002
                    shock = -0.07 if symbol == "TLT" and index % 31 == 20 else 0.0
                    rebound = 0.025 if symbol == "TLT" and index % 31 in (21, 22, 23) else 0.0
                    close = previous * (1.0 + wave + shock + rebound)
                    open_price = previous * (1.0 + wave * 0.25)
                    prices[symbol] = close
                    rows.append({
                        "date": current.isoformat(),
                        "timestamp_utc": f"{current.isoformat()}T05:00:00Z",
                        "symbol": symbol,
                        "open": open_price,
                        "high": max(open_price, close) * 1.001,
                        "low": min(open_price, close) * 0.999,
                        "close": close,
                        "volume": 1000000,
                        "trade_count": 1000,
                        "vwap": (open_price + close) / 2.0,
                        "feed": "SIP",
                        "adjustment": "ALL",
                    })
                index += 1
            current += timedelta(days=1)
        with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_campaign_is_frozen_and_inert(self):
        campaign = load_campaign(Path("config/campaigns/cross_asset_short_term_reversal_v1.json"))
        exact = campaign["exact_specification"]
        self.assertEqual(exact["primary_trigger_z_at_or_below"], -1.5)
        self.assertEqual(exact["holding_sessions"], 3)
        self.assertFalse(exact["parameter_sweeps_allowed"])
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_event_construction_is_causal_non_overlapping_and_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.csv.gz"
            self._write_prices(path)
            dates, panel = load_daily_panel(path)
            events = build_events(
                dates,
                panel,
                lookback_sessions=5,
                volatility_sessions=20,
                trigger_z=-1.5,
                holding_sessions=3,
            )
        self.assertGreater(len(events), 10)
        self.assertTrue(any(event["primary_symbol"] == "TLT" for event in events))
        for prior, current in zip(events, events[1:]):
            self.assertGreaterEqual(current["decision_date"], prior["exit_date"])
        for event in events:
            self.assertEqual(event["random_symbol"], _fixed_random_symbol(event["decision_date"]))
            self.assertIn(event["primary_symbol"], RISKY_SYMBOLS)
            self.assertLessEqual(event["primary_z"], -1.5)

    def test_evaluation_is_deterministic_and_never_promotable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.csv.gz"
            self._write_prices(path)
            campaign = json.loads(
                Path("config/campaigns/cross_asset_short_term_reversal_v1.json").read_text(encoding="utf-8")
            )
            first = evaluate(path, campaign)
            second = evaluate(path, campaign)
        self.assertEqual(first, second)
        self.assertFalse(first["promotion_eligible"])
        self.assertFalse(first["authority"]["automatic_execution"])
        self.assertIn(first["status"], {"HISTORICAL_GATE_FAIL", "HISTORICAL_GATE_PASS_REQUIRES_HUMAN_REVIEW"})


if __name__ == "__main__":
    unittest.main()
