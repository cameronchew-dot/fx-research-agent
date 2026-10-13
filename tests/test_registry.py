import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.registry import import_genesis, status
from fx_research_agent.storage import initialize


class RegistryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

