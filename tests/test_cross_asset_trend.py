import csv
import gzip
import json
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fx_research_agent.campaigns import load_campaign
from fx_research_agent.cross_asset_trend import (
    ALL_SYMBOLS,
    ASSET_CLASSES,
    ASSET_WEIGHT_CAP,
    CLASS_WEIGHT_CAPS,
    evaluate,
    load_adjusted_prices,
    target_series,
)


class CrossAssetTrendTests(unittest.TestCase):
    def _write_prices(self, path: Path, observations: int = 1200) -> None:
        with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "symbol", "adjusted_close"])
            writer.writeheader()
            current = date(2005, 1, 3)
            index = 0
            while index < observations:
                if current.weekday() < 5:
                    for offset, symbol in enumerate(ALL_SYMBOLS):
                        drift = 0.00003 * (offset - 2) if symbol != "BIL" else 0.00001
                        value = (50 + offset * 10) * math.exp(index * drift + math.sin(index / (40 + offset)) * 0.002)
                        writer.writerow({"date": current.isoformat(), "symbol": symbol, "adjusted_close": value})
                    index += 1
                current += timedelta(days=1)

    def test_campaign_is_one_inert_non_promotable_specification(self):
        campaign = load_campaign(Path("config/campaigns/cross_asset_etf_trend_v1.json"))
        self.assertEqual(campaign["exact_specification"]["trend_lookback_common_trading_days"], 252)
        self.assertFalse(campaign["exact_specification"]["parameter_sweeps_allowed"])
        self.assertTrue(campaign["review_gates"]["independent_adjusted_price_source_required_for_promotion"])
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_targets_are_causal_and_respect_asset_and_class_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.csv.gz"
            self._write_prices(path)
            days, panel = load_adjusted_prices(path)
            targets = target_series(days, panel)
        self.assertGreater(len(targets), 20)
        first = targets[0]
        self.assertLess(first["decision_date"], first["effective_date"])
        self.assertLessEqual(max(first["PRIMARY"].values()), ASSET_WEIGHT_CAP + 1e-12)
        for asset_class, cap in CLASS_WEIGHT_CAPS.items():
            actual = sum(weight for symbol, weight in first["PRIMARY"].items() if ASSET_CLASSES[symbol] == asset_class)
            self.assertLessEqual(actual, cap + 1e-12)

    def test_evaluation_is_deterministic_and_never_promotable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.csv.gz"
            self._write_prices(path)
            first = evaluate(path)
            second = evaluate(path)
        self.assertEqual(first, second)
        self.assertGreater(first["portfolio_month_count"], 20)
        self.assertFalse(first["promotion_eligible"])
        self.assertEqual(set(first["controls_dated_confirmation"]), {"opposite", "stale", "random", "buy_hold"})

    def test_genesis_hypothesis_exists(self):
        registry = json.loads(Path("config/genesis_hypotheses.json").read_text(encoding="utf-8"))
        row = next(item for item in registry["hypotheses"] if item["hypothesis_id"] == "HYP_CROSS_ASSET_ETF_TREND_V1")
        self.assertEqual(row["state"], "REJECTED")
        self.assertIn("FAILED_STALE_CONTROL", row["next_action"])

        delayed = next(
            item
            for item in registry["hypotheses"]
            if item["hypothesis_id"] == "HYP_CROSS_ASSET_ETF_DELAYED_TREND_CONFIRMATION_V2"
        )
        self.assertEqual(delayed["state"], "PROPOSED")
        self.assertIn("NO_REUSE_OF_V1_DATED_WINDOW_AS_V2_CONFIRMATION", delayed["dependencies"])


if __name__ == "__main__":
    unittest.main()
