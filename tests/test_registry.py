import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.registry import hypothesis_state, import_genesis, review_hypothesis, status
from fx_research_agent.storage import initialize, insert_immutable, payload_hash


class RacingConnection:
    def __init__(self, digest):
        self.digest = digest
        self.select_count = 0

    def execute(self, sql, values):
        if sql.startswith("SELECT payload_hash"):
            self.select_count += 1
            return RacingCursor(None if self.select_count == 1 else {"payload_hash": self.digest})
        if sql.startswith("INSERT INTO"):
            raise sqlite3.IntegrityError("simulated concurrent immutable insert")
        raise AssertionError(sql)

    def commit(self):
        raise AssertionError("idempotent raced insert must not commit a new row")


class RacingCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class RegistryTests(unittest.TestCase):
    def test_concurrent_identical_immutable_insert_is_idempotent(self):
        payload = {"snapshot_id": "S1", "value": 1}
        connection = RacingConnection(payload_hash(payload))
        inserted = insert_immutable(
            connection,
            "campaign_progress_snapshots",
            "snapshot_id",
            "S1",
            payload,
            {"campaign_id": "C1", "observed_at_utc": "2026-10-15T00:00:00Z"},
        )
        self.assertFalse(inserted)

    def test_genesis_import_is_idempotent_and_conflicts_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            payload = {
                "schema": "EUR_AGENT_RESEARCH_HYPOTHESIS_REGISTRY_V1",
                "hypotheses": [
                    {
                        "hypothesis_id": "HYP_1",
                        "proposed_at_utc": "2026-10-12T00:00:00Z",
                        "state": "PROPOSED",
                        "priority": 1,
                    }
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)

            first = import_genesis(connection, path, "repo", "commit", "path", "2026-10-13T00:00:00Z")
            second = import_genesis(connection, path, "repo", "commit", "path", "2026-10-13T00:00:01Z")
            self.assertEqual(first, {"inserted": 1, "unchanged": 0})
            self.assertEqual(second, {"inserted": 0, "unchanged": 1})
            self.assertEqual(status(connection)["hypothesis_count"], 1)

            payload["hypotheses"][0]["state"] = "REJECTED"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "conflicting immutable rewrite"):
                import_genesis(connection, path, "repo", "commit", "path")

    def test_human_review_is_append_only_and_cannot_create_campaign(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        initialize(connection)
        hypothesis = {"hypothesis_id": "HYP_AUTO_1", "state": "PROPOSED"}
        connection.execute(
            "INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?)",
            ("HYP_AUTO_1", "hash", json.dumps(hypothesis), "LOCAL_AUTONOMOUS_PROPOSER", "model", "run", "2026-10-13T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO hypothesis_events VALUES (?,?,?,?,?,?,?,?)",
            ("HYP_AUTO_1:PROPOSED", "HYP_AUTO_1", "PROPOSED", "2026-10-13T00:00:00Z", "GOVERNED_PROPOSER", "proposed", "hash", "{}"),
        )
        connection.commit()
        result = review_hypothesis(
            connection,
            "HYP_AUTO_1",
            decision="REJECT",
            reviewed_by="CAMERON",
            reason="Not sufficiently distinct",
            reviewed_at_utc="2026-10-14T00:00:00Z",
        )
        self.assertEqual(hypothesis_state(connection, "HYP_AUTO_1"), "REJECTED")
        self.assertFalse(result["campaign_created"])
        self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM research_campaigns").fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()

