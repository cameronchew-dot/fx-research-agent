import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fx_research_agent.sector_etf_reversal import (
    build_session_rows,
    evaluate,
    newey_west_t_stat,
    summarize,
)


NEW_YORK = ZoneInfo("America/New_York")
SECTORS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY")


def bar(day, clock, *, open_price, close_price):
    local = datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=NEW_YORK)
    return {
        "timestamp_utc": local.astimezone(ZoneInfo("UTC")),
        "open": float(open_price),
        "high": float(max(open_price, close_price)),
        "low": float(min(open_price, close_price)),
        "close": float(close_price),
    }


def synthetic_panel():
    days = ("2026-11-02", "2026-11-03", "2026-11-04")
    output = {}
    for symbol_index, symbol in enumerate(SECTORS + ("SPY",)):
        rows = []
        for day_index, day in enumerate(days):
            opening = 100.0
            if day_index == 1 and symbol == "XLE":
                opening = 98.0
            elif day_index == 1 and symbol == "XLK":
                opening = 102.0
            elif day_index == 2 and symbol == "XLF":
                opening = 97.0
            entry = opening
            close_1015 = opening + (1.0 if symbol in {"XLE", "XLF"} else symbol_index / 100.0)
            rows.extend(
                [
                    bar(day, "09:30", open_price=opening, close_price=opening),
                    bar(day, "09:45", open_price=entry, close_price=entry),
                    bar(day, "10:15", open_price=close_1015, close_price=close_1015),
                    bar(day, "15:45", open_price=100.0, close_price=100.0),
                ]
            )
        output[symbol] = sorted(rows, key=lambda row: row["timestamp_utc"])
    return output


class SectorEtfReversalTests(unittest.TestCase):
    def test_campaign_is_frozen_inert_and_family_corrected(self):
        campaign = json.loads(
            Path("config/campaigns/sector_etf_cross_sectional_overnight_reversal_v1.json").read_text()
        )
        self.assertEqual(tuple(campaign["population"]["sector_universe"]), SECTORS)
        self.assertFalse(campaign["exact_specification"]["parameter_sweeps_allowed"])
        self.assertEqual(
            campaign["review_gates"]["validation_plus_dated_primary_newey_west_t_stat_minimum"],
            2.24,
        )
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_cross_sectional_selection_is_causal_and_one_per_day(self):
        rows = build_session_rows(
            synthetic_panel(),
            sector_universe=SECTORS,
            market_control="SPY",
            campaign_id="TEST",
            start_date="2026-11-01",
            end_date="2026-11-05",
        )
        self.assertEqual([row["date"] for row in rows], ["2026-11-03", "2026-11-04"])
        self.assertEqual(rows[0]["selected_symbol"], "XLE")
        self.assertEqual(rows[0]["winner_symbol"], "XLK")
        self.assertEqual(rows[1]["selected_symbol"], "XLF")
        self.assertTrue(all(row["primary_active"] for row in rows))
        self.assertGreater(rows[0]["primary_gross_return"], 0.0)
        metrics = summarize(rows, "primary", 0.0)
        self.assertEqual(metrics["event_count"], 2)
        self.assertEqual(metrics["events_per_week"], 5.0)

    def test_newey_west_t_stat_has_expected_direction(self):
        positive = [0.005 + (index % 3) * 0.001 for index in range(20)]
        self.assertGreater(newey_west_t_stat(positive), 0)
        self.assertLess(newey_west_t_stat([-value for value in positive]), 0)

    def test_evaluation_is_deterministic_and_never_promotable(self):
        campaign = json.loads(
            Path("config/campaigns/sector_etf_cross_sectional_overnight_reversal_v1.json").read_text()
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for symbol, rows in synthetic_panel().items():
                path = Path(directory) / f"{symbol}.csv.gz"
                paths[symbol] = path
                with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                    fields = ["timestamp_utc", "symbol", "open", "high", "low", "close"]
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    for row in rows:
                        writer.writerow(
                            {
                                "timestamp_utc": row["timestamp_utc"].isoformat().replace("+00:00", "Z"),
                                "symbol": symbol,
                                "open": row["open"],
                                "high": row["high"],
                                "low": row["low"],
                                "close": row["close"],
                            }
                        )
            first = evaluate(paths, campaign)
            second = evaluate(paths, campaign)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "HISTORICAL_GATE_FAIL")
        self.assertFalse(first["promotion_eligible"])
        self.assertFalse(first["llm_forward_shadow_eligible"])

    def test_sealed_historical_result_stays_rejected(self):
        result = json.loads(
            Path("data/results/sector_etf_cross_sectional_overnight_reversal_v1.json").read_text()
        )
        self.assertEqual(result["status"], "HISTORICAL_GATE_FAIL")
        self.assertFalse(result["all_cost_scenarios_passed"])
        self.assertFalse(result["promotion_eligible"])
        self.assertFalse(result["llm_forward_shadow_eligible"])
        self.assertTrue(all(not value for value in result["authority"].values()))

        primary = result["cost_scenarios"]["primary"]
        combined = primary["validation_plus_dated"]["primary"]
        self.assertFalse(primary["passed"])
        self.assertEqual(combined["event_count"], 1077)
        self.assertAlmostEqual(combined["events_per_week"], 4.457781456953642)
        self.assertAlmostEqual(combined["average_gross_return_per_event"], -1.53027160667342e-05)
        self.assertAlmostEqual(combined["average_net_return_per_event"], -0.0004153027160667342)
        self.assertAlmostEqual(combined["newey_west_t_stat"], -2.5863550254206755)
        self.assertTrue(all(
            primary["gates"][name]
            for name in (
                "minimum_primary_events_development",
                "minimum_primary_events_chronological_validation",
                "minimum_primary_events_dated_confirmation",
            )
        ))
        self.assertTrue(all(
            not value
            for name, value in primary["gates"].items()
            if not name.startswith("minimum_primary_events_")
        ))

        self.assertEqual(
            result["provenance"]["bars_sha256"],
            {
                "SPY": "db783a192931624c928dbfac1c4f2697d65a3aa6b67b4703efbd09b0af1b9618",
                "XLB": "aece4869260f235a7111543accc0a34c920a9837d2d79d49c68e925f974becbc",
                "XLE": "77fb9e076180708c0a3f4cdb736f01c2984c57b415eeb18d9d354bbb632d77a3",
                "XLF": "29d5a0836aabdb8cb7d25a086c65138a331efa1edb32d271ced4b224a3523f17",
                "XLI": "1aa5b65c3f0bfbb4a9f9f47a38bbfc49a092b0fc33751cd963b654058372b01b",
                "XLK": "31cbc0c49771fc915e1d97649d66b524250ab8726f5285c905db699117be3e42",
                "XLP": "cf4c8d636ae69f13b625d54f6ea6b06185e77f7783d3b93c701447ed2e1ed390",
                "XLU": "420e5c02a760ea559b9373af9b5e87d2a21d3faa6eab6d4977b638bde8e79a4b",
                "XLV": "d0e2c70fa7aee0bfc5f207c1df491eea112ec8e325c69e0234ebd4d2e578e4f6",
                "XLY": "477d0ef7591d729fc65d4ea3c370dbba2c3cc3d7320aab84d251dd97be8aaa07",
            },
        )


if __name__ == "__main__":
    unittest.main()
