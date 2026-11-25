import unittest
from datetime import datetime, timedelta, timezone

from fx_research_agent.regime_enrichment import (
    _garch,
    _history_as_of,
    _hmm,
    _markov,
    parse_utc,
)
from fx_research_agent.signal_context_forensics import _apply_regime_enrichment


def candles(start: datetime, count: int, minutes: int) -> list[dict]:
    rows = []
    price = 1.08
    for index in range(count):
        end = start + timedelta(minutes=minutes * (index + 1))
        move = ((index % 11) - 5) * 0.00001
        close = price + move
        rows.append(
            {
                "end_time_utc": end.isoformat().replace("+00:00", "Z"),
                "open": price,
                "high": max(price, close) + 0.0002,
                "low": min(price, close) - 0.0002,
                "close": close,
                "volume": 100 + index % 17,
            }
        )
        price = close
    return rows


class RegimeEnrichmentTests(unittest.TestCase):
    def test_future_candles_cannot_change_prior_regime_labels(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        m15 = candles(start, 600, 15)
        h1 = candles(start - timedelta(days=20), 650, 60)
        decision = parse_utc(m15[399]["end_time_utc"])

        def states(m15_rows, h1_rows):
            m15_history = _history_as_of(
                m15_rows,
                [parse_utc(row["end_time_utc"]) for row in m15_rows],
                decision,
            )
            h1_history = _history_as_of(
                h1_rows,
                [parse_utc(row["end_time_utc"]) for row in h1_rows],
                decision,
            )
            self.assertTrue(
                all(parse_utc(row["end_time_utc"]) <= decision for row in m15_history)
            )
            self.assertTrue(
                all(parse_utc(row["end_time_utc"]) <= decision for row in h1_history)
            )
            return (
                _markov(m15_history, 0.0001),
                _hmm(m15_history, 0.0001),
                _garch(h1_history, 0.0001),
            )

        expected = states(m15, h1)
        changed_m15 = [dict(row) for row in m15]
        changed_h1 = [dict(row) for row in h1]
        for row in changed_m15:
            if parse_utc(row["end_time_utc"]) > decision:
                row.update({"open": 2.0, "high": 2.2, "low": 1.8, "close": 2.1})
        for row in changed_h1:
            if parse_utc(row["end_time_utc"]) > decision:
                row.update({"open": 2.0, "high": 2.2, "low": 1.8, "close": 2.1})
        self.assertEqual(expected, states(changed_m15, changed_h1))
        self.assertEqual(expected[0]["status"], "READY_HISTORICAL_CAUSAL")
        self.assertEqual(
            expected[1]["status"], "READY_HISTORICAL_CAUSAL_RESEARCH_ONLY"
        )
        self.assertEqual(expected[2]["status"], "READY_HISTORICAL_CAUSAL")

    def test_enrichment_is_additive_and_requires_matching_decision_time(self):
        event = {"decision_time_utc": "2026-01-02T00:00:00Z"}
        enrichment = {
            "status": "READY",
            "decision_time_utc": event["decision_time_utc"],
            "model_contract_sha256": "contract",
            "source_manifest_set_sha256": "sources",
            "markov": {"state_id": "LONDON|UP|NORMAL"},
            "hmm": {"state_id": "HMM_UP_NORMAL_NORMALVOL"},
            "garch": {"volatility_state": "LOW"},
        }
        original = {"session_bucket": "LONDON"}
        result = _apply_regime_enrichment(original, event, enrichment)
        self.assertEqual(original, {"session_bucket": "LONDON"})
        self.assertEqual(result["markov_state"], "LONDON|UP|NORMAL")
        self.assertTrue(
            result["historical_regime_enrichment"][
                "historical_causal_not_forward"
            ]
        )
        with self.assertRaisesRegex(ValueError, "decision time"):
            _apply_regime_enrichment(
                original,
                event,
                {**enrichment, "decision_time_utc": "2026-01-03T00:00:00Z"},
            )


if __name__ == "__main__":
    unittest.main()
