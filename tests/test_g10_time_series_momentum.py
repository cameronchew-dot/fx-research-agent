import csv
import gzip
import json
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fx_research_agent.campaigns import load_campaign
from fx_research_agent.g10_time_series_momentum import (
    INSTRUMENTS,
    NET_USD_FACTOR_CAP,
    PAIR_WEIGHT_CAP,
    evaluate,
    load_daily_spot,
    target_series,
)


class G10TimeSeriesMomentumTests(unittest.TestCase):
    def _write_spot(self, path: Path, observations: int = 900) -> None:
        with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["date", "instrument", "normalized_usd_per_foreign_currency"],
            )
            writer.writeheader()
            current = date(2000, 1, 3)
            index = 0
            while index < observations:
                if current.weekday() < 5:
                    for offset, instrument in enumerate(INSTRUMENTS):
                        drift = (offset - 3) * 0.00002
                        cycle = math.sin(index / (35 + offset)) * 0.0004
                        price = (1.0 + offset * 0.1) * math.exp(index * drift + cycle)
                        writer.writerow(
                            {
                                "date": current.isoformat(),
                                "instrument": instrument,
                                "normalized_usd_per_foreign_currency": price,
                            }
                        )
                    index += 1
                current += timedelta(days=1)

    def test_campaign_is_locked_inert_and_financing_blocked(self):
        campaign = load_campaign(
            Path("config/campaigns/g10_daily_time_series_momentum_spot_diagnostic_v1.json")
        )
        self.assertEqual(campaign["exact_specification"]["lookback_common_trading_days"], [21, 63, 126])
        self.assertFalse(campaign["exact_specification"]["parameter_sweeps_allowed"])
        self.assertTrue(campaign["review_gates"]["historical_financing_required_for_any_promotion"])
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_targets_are_causal_and_respect_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spot.csv.gz"
            self._write_spot(path)
            days, panel = load_daily_spot(path)
            targets = target_series(days, panel)
        self.assertGreater(len(targets), 100)
        first = targets[0]
        self.assertLess(first["decision_date"], first["effective_date"])
        self.assertLessEqual(max(abs(value) for value in first["PRIMARY"].values()), PAIR_WEIGHT_CAP + 1e-12)
        self.assertLessEqual(abs(sum(first["PRIMARY"].values())), NET_USD_FACTOR_CAP + 1e-12)

    def test_evaluation_is_deterministic_and_never_promotable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spot.csv.gz"
            self._write_spot(path)
            first = evaluate(path)
            second = evaluate(path)
        self.assertEqual(first, second)
        self.assertGreater(first["portfolio_week_count"], 100)
        self.assertFalse(first["promotion_eligible"])
        self.assertEqual(first["promotion_blockers"], ["HISTORICAL_FINANCING_OR_FORWARD_POINTS_UNAVAILABLE"])
        self.assertEqual(set(first["controls_dated_confirmation"]), {"opposite", "stale", "random", "usd_factor"})

    def test_genesis_hypothesis_is_closed_without_authority(self):
        registry = json.loads(Path("config/genesis_hypotheses.json").read_text(encoding="utf-8"))
        row = next(
            item
            for item in registry["hypotheses"]
            if item["hypothesis_id"] == "HYP_G10_DAILY_TIME_SERIES_MOMENTUM_SPOT_DIAGNOSTIC_V1"
        )
        self.assertEqual(row["state"], "REJECTED")
        self.assertEqual(row["next_action"], "CLOSED_FAILED_DATED_CONFIRMATION_AND_CONTROLS_DO_NOT_RETUNE")


if __name__ == "__main__":
    unittest.main()
