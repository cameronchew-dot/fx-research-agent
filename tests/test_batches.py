import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.batches import add_campaign_to_batch, load_batch, register_batch
from fx_research_agent.storage import initialize


class BatchTests(unittest.TestCase):
    def _payload(self):
        return {
            "schema": "FX_RESEARCH_BATCH_V1",
            "batch_id": "BATCH_1",
            "created_at_utc": "2026-10-13T00:00:00Z",
            "title": "Three-slot batch",
            "instrument": "EUR_USD",
            "maximum_active_campaigns": 3,
            "campaign_ids": ["C1"],
            "slot_policy": [],
            "multiplicity_policy": {
                "method": "HOLM_BONFERRONI",
                "familywise_alpha": 0.05,
                "hypothesis_budget": 3,
            },
            "authority": {
                "automatic_campaign_addition": False,
                "automatic_approval": False,
                "automatic_promotion": False,
                "downstream_authority": False,
            },
        }

    def test_batch_is_capped_and_registration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            payload = self._payload()
            path.write_text(json.dumps(payload), encoding="utf-8")
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            connection.execute(
                "INSERT INTO research_campaigns VALUES (?,?,?,?)",
                ("C1", "hash", "{}", "2026-10-13T00:00:00Z"),
            )
            connection.commit()
            first = register_batch(connection, path)
            second = register_batch(connection, path)
        self.assertTrue(first["inserted"])
        self.assertFalse(second["inserted"])
        self.assertEqual(first["available_slot_count"], 2)

    def test_more_than_batch_cap_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            payload = self._payload()
            payload["campaign_ids"] = ["C1", "C2", "C3", "C4"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exceeds"):
                load_batch(path)

    def test_seven_slot_literature_batch_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            payload = self._payload()
            payload["maximum_active_campaigns"] = 7
            payload["multiplicity_policy"]["hypothesis_budget"] = 7
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_batch(path)
        self.assertEqual(loaded["maximum_active_campaigns"], 7)

    def test_more_than_ten_slots_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            payload = self._payload()
            payload["maximum_active_campaigns"] = 11
            payload["multiplicity_policy"]["hypothesis_budget"] = 11
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "between one and ten"):
                load_batch(path)

    def test_named_human_can_fill_remaining_slots_without_rewriting_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            path.write_text(json.dumps(self._payload()), encoding="utf-8")
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            for campaign_id in ("C1", "C2"):
                connection.execute(
                    "INSERT INTO research_campaigns VALUES (?,?,?,?)",
                    (campaign_id, "hash", "{}", "2026-10-13T00:00:00Z"),
                )
            connection.execute(
                "INSERT INTO campaign_events VALUES (?,?,?,?,?,?,?,?)",
                ("C2:APPROVED", "C2", "APPROVED", "2026-10-13T01:00:00Z", "CAMERON", "reviewed", "hash", "{}"),
            )
            connection.commit()
            register_batch(connection, path)
            result = add_campaign_to_batch(
                connection,
                "BATCH_1",
                "C2",
                added_by="CAMERON",
                reason="Distinct predeclared mechanism",
                added_at_utc="2026-10-13T02:00:00Z",
            )
        self.assertTrue(result["inserted"])
        self.assertEqual(result["occupied_slot_count"], 2)
        self.assertEqual(result["available_slot_count"], 1)


if __name__ == "__main__":
    unittest.main()
