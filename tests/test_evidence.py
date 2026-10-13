import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.evidence import evidence_status, sync_evidence_exports, validate_manifest
from fx_research_agent.storage import initialize


class EvidenceTests(unittest.TestCase):
    def _write_export(self, root: Path, payload: dict) -> Path:
        payload_path = root / "evidence.payload.json.gz"
        with gzip.open(payload_path, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle)
        manifest = {
            "manifest_id": "EVIDENCE_1",
            "schema": "FX_RESEARCH_EVIDENCE_EXPORT_V1",
            "created_at_utc": "2026-10-13T00:00:00Z",
            "source_system": "EUR_AGENT_FORWARD_EVIDENCE",
            "instrument": "EUR_USD",
            "window_start_utc": "2026-10-12T00:00:00Z",
            "window_end_utc": "2026-10-13T00:00:00Z",
            "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
            "payload_path": payload_path.name,
            "freshness_status": "FRESH",
            "gap_status": "COMPLETE",
            "data_classes": payload["data_classes"],
            "row_counts": {"candidate_episode_facts": 1},
        }
        manifest_path = root / "evidence.manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def _payload(self) -> dict:
        return {
            "schema": "FX_RESEARCH_EVIDENCE_PAYLOAD_V1",
            "manifest_id": "EVIDENCE_1",
            "data_classes": ["FORWARD_FAILED_AUCTION_EPISODES", "FORWARD_RULE_BASELINE_OUTCOMES"],
            "candidate_episode_facts": [{"candidate_id": "C1", "episode_id": "E1"}],
            "rule_baseline_outcome_facts": [{"outcome_id": "O1", "realized_net_r": 0.5}],
        }

    def test_sanitized_evidence_is_accepted_and_sync_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            path = self._write_export(source, self._payload())
            self.assertEqual(validate_manifest(path)["manifest_id"], "EVIDENCE_1")
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            first = sync_evidence_exports(connection, source, root / "inbox")
            second = sync_evidence_exports(connection, source, root / "inbox")
            status = evidence_status(connection)
        self.assertEqual(first["inserted_count"], 1)
        self.assertEqual(second["unchanged_count"], 1)
        self.assertEqual(status["research_evidence_status"], "READY")
        self.assertIn("FORWARD_RULE_BASELINE_OUTCOMES", status["available_data_classes"])

    def test_sensitive_decision_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = self._payload()
            payload["candidate_episode_facts"][0]["prompt_text"] = "secret"
            path = self._write_export(root, payload)
            with self.assertRaisesRegex(ValueError, "prohibited fields"):
                validate_manifest(path)

    def test_unknown_data_class_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = self._payload()
            payload["data_classes"].append("UNREVIEWED_AGENT_POLICY")
            path = self._write_export(root, payload)
            with self.assertRaisesRegex(ValueError, "unsupported data classes"):
                validate_manifest(path)


if __name__ == "__main__":
    unittest.main()
