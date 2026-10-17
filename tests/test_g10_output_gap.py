import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.campaigns import load_campaign
from fx_research_agent.g10_economic_momentum import CURRENCIES
from fx_research_agent.g10_output_gap import evaluate, hamilton_gap
from fx_research_agent.g10_value import INSTRUMENT_CURRENCY


class G10OutputGapTests(unittest.TestCase):
    def test_campaign_is_one_inert_recursive_specification(self):
        campaign = load_campaign(Path("config/campaigns/g10_recursive_output_gap_v1.json"))
        exact = campaign["exact_specification"]
        self.assertEqual(exact["minimum_regression_observations"], 60)
        self.assertEqual(exact["information_lag_months"], 2)
        self.assertFalse(exact["parameter_sweeps_allowed"])
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_hamilton_gap_cannot_see_future_observations(self):
        series = {index: 100 + index + ((index % 7) - 3) * .2 for index in range(150)}
        original = hamilton_gap(series, 110)
        series.update({index: 100000 + index for index in range(111, 150)})
        self.assertAlmostEqual(original, hamilton_gap(series, 110), places=14)

    def test_pipeline_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spot, production = root / "spot.gz", root / "production.gz"
            instrument_by_currency = {currency: instrument for instrument, currency in INSTRUMENT_CURRENCY.items()}
            with gzip.open(spot, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["month", "instrument", "normalized_usd_per_foreign_currency"])
                writer.writeheader()
                for index in range(210):
                    month = f"{2000 + index // 12:04d}-{index % 12 + 1:02d}"
                    for offset, currency in enumerate(CURRENCIES):
                        writer.writerow({"month": month, "instrument": instrument_by_currency[currency], "normalized_usd_per_foreign_currency": 1 + offset * .1 + index * (offset + 1) * .001})
            with gzip.open(production, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["month", "currency", "industrial_production_index"])
                writer.writeheader()
                for index in range(210):
                    month = f"{2000 + index // 12:04d}-{index % 12 + 1:02d}"
                    for offset, currency in enumerate((*CURRENCIES, "USD")):
                        writer.writerow({"month": month, "currency": currency, "industrial_production_index": 100 + index * (offset + 1) * .1 + (index % (offset + 3)) * .05})
            first, second = evaluate(spot, production), evaluate(spot, production)
        self.assertEqual(first, second)
        self.assertGreater(first["portfolio_month_count"], 100)

    def test_registry_starts_campaign_proposed(self):
        registry = json.loads(Path("config/genesis_hypotheses.json").read_text(encoding="utf-8"))
        states = {row["hypothesis_id"]: row["state"] for row in registry["hypotheses"]}
        self.assertEqual(states["HYP_G10_RECURSIVE_OUTPUT_GAP_V1"], "PROPOSED")


if __name__ == "__main__":
    unittest.main()
