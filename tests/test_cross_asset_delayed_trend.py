import csv
import gzip
import json
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fx_research_agent.cross_asset_delayed_trend import (
    STRATEGY_ID,
    append_forward_ledger,
    evaluate_delayed,
)
from fx_research_agent.campaigns import load_campaign
from fx_research_agent.cross_asset_trend import ALL_SYMBOLS, evaluate


class CrossAssetDelayedTrendTests(unittest.TestCase):
    def _write_prices(self, path: Path, observations: int = 1500) -> None:
        with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "symbol", "adjusted_close"])
            writer.writeheader()
            current = date(2005, 1, 3)
            index = 0
            while index < observations:
                if current.weekday() < 5:
                    for offset, symbol in enumerate(ALL_SYMBOLS):
                        drift = 0.00002 * (offset - 2) if symbol != "BIL" else 0.00001
                        cycle = math.sin(index / (35 + offset)) * 0.004
                        value = (50 + offset * 10) * math.exp(index * drift + cycle)
                        writer.writerow({"date": current.isoformat(), "symbol": symbol, "adjusted_close": value})
                    index += 1
                current += timedelta(days=1)

    def test_delayed_evaluation_separates_replication_from_forward_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prices = root / "prices.csv.gz"
            reference = root / "v1.json"
            self._write_prices(prices)
            reference.write_text(json.dumps(evaluate(prices)), encoding="utf-8")
            result = evaluate_delayed(prices, reference, forward_start="2099-01-01")

        self.assertTrue(result["cross_source_replication"]["passed"])
        self.assertEqual(result["status"], "FORWARD_ACCUMULATION")
        self.assertEqual(result["forward"]["metrics"]["month_count"], 0)
        self.assertFalse(result["promotion_eligible"])
        self.assertFalse(result["authority"]["order_authority"])

    def test_ledger_is_idempotent_and_rejects_conflicting_rewrites(self):
        row = {
            "decision_date": "2026-11-30",
            "entry_date": "2026-12-01",
            "exit_date": "2027-01-04",
            "net_return": 0.01,
            "cash_return": 0.001,
            "excess_cash_return": 0.009,
            "risky_gross_weight": 0.75,
            "cash_weight": 0.25,
            "turnover": 0.5,
            "cost_return": 0.0005,
            "active_assets": ["SPY", "IEF"],
        }
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.jsonl"
            self.assertEqual(append_forward_ledger(ledger, [row], source_sha256="a" * 64), 1)
            self.assertEqual(append_forward_ledger(ledger, [row], source_sha256="b" * 64), 0)
            conflicting = {**row, "net_return": 0.02}
            with self.assertRaisesRegex(ValueError, "conflicting immutable forward result"):
                append_forward_ledger(ledger, [conflicting], source_sha256="c" * 64)
            record = json.loads(ledger.read_text(encoding="utf-8"))

        self.assertEqual(record["strategy"], STRATEGY_ID)
        self.assertEqual(record["payload"]["net_return"], 0.01)

    def test_campaign_is_forward_only_and_inert(self):
        campaign = load_campaign(Path("config/campaigns/cross_asset_etf_delayed_trend_v2.json"))
        self.assertEqual(campaign["exact_specification"]["forward_start"], "2026-12-01")
        self.assertEqual(
            campaign["evidence_roles"]["v1_yahoo_dated_window"],
            "SELECTION_EVIDENCE_NOT_V2_CONFIRMATION",
        )
        self.assertFalse(campaign["exact_specification"]["parameter_sweeps_allowed"])
        self.assertFalse(campaign["authority"]["order_authority"])


if __name__ == "__main__":
    unittest.main()
