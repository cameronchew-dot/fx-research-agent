import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.campaigns import load_campaign
from fx_research_agent.g10_economic_momentum import CURRENCIES, evaluate
from fx_research_agent.g10_value import INSTRUMENT_CURRENCY


class G10EconomicMomentumTests(unittest.TestCase):
    def test_campaign_is_one_inert_specification(self):
        campaign = load_campaign(Path("config/campaigns/g10_industrial_production_momentum_v1.json"))
        self.assertEqual(campaign["exact_specification"]["formation_months"], 60)
        self.assertFalse(campaign["exact_specification"]["parameter_sweeps_allowed"])
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_pipeline_is_deterministic_and_lagged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spot, production = root / "spot.gz", root / "production.gz"
            instrument_by_currency = {currency: instrument for instrument, currency in INSTRUMENT_CURRENCY.items()}
            with gzip.open(spot, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["month", "instrument", "normalized_usd_per_foreign_currency"])
                writer.writeheader()
                for index in range(180):
                    month = f"{2000 + index // 12:04d}-{index % 12 + 1:02d}"
                    for offset, currency in enumerate(CURRENCIES):
                        writer.writerow({"month": month, "instrument": instrument_by_currency[currency], "normalized_usd_per_foreign_currency": 1 + offset * .1 + index * (offset + 1) * .001})
            with gzip.open(production, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["month", "currency", "industrial_production_index"])
                writer.writeheader()
                for index in range(180):
                    month = f"{2000 + index // 12:04d}-{index % 12 + 1:02d}"
                    for offset, currency in enumerate(CURRENCIES):
                        writer.writerow({"month": month, "currency": currency, "industrial_production_index": 100 + index * (offset + 1) * .1})
            first = evaluate(spot, production)
            second = evaluate(spot, production)
        self.assertEqual(first, second)
        self.assertGreater(first["portfolio_month_count"], 100)
        self.assertEqual(first["rows"][0]["month"], "2005-03")


if __name__ == "__main__":
    unittest.main()
