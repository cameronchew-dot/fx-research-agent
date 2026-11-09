import unittest

from ops.cross_asset_twelve_data_extract import normalize_payload


class TwelveDataExtractTests(unittest.TestCase):
    def test_normalizes_adjusted_daily_payload_without_credentials(self):
        rows, meta = normalize_payload(
            "SPY",
            {
                "meta": {
                    "symbol": "SPY",
                    "currency": "USD",
                    "exchange_timezone": "America/New_York",
                },
                "values": [
                    {"datetime": "2026-11-06", "close": "681.25"},
                    {"datetime": "2026-11-05", "close": "679.50"},
                ],
                "status": "ok",
            },
        )
        self.assertEqual([row["date"] for row in rows], ["2026-11-05", "2026-11-06"])
        self.assertEqual(rows[0]["source"], "TWELVE_DATA_TIME_SERIES_ADJUST_ALL")
        self.assertEqual(meta["symbol"], "SPY")

    def test_rejects_provider_errors_and_duplicates(self):
        with self.assertRaisesRegex(ValueError, "response error"):
            normalize_payload("SPY", {"status": "error", "message": "bad key"})
        with self.assertRaisesRegex(ValueError, "duplicate adjusted close"):
            normalize_payload(
                "SPY",
                {
                    "meta": {"symbol": "SPY"},
                    "values": [
                        {"datetime": "2026-11-06", "close": "1"},
                        {"datetime": "2026-11-06", "close": "2"},
                    ],
                },
            )


if __name__ == "__main__":
    unittest.main()
