import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.result_packages import register_package, result_status, sync_packages, validate_package
from fx_research_agent.storage import initialize


class ResultPackageTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        initialize(self.connection)

    def tearDown(self):
        self.connection.close()

    def _package(self, root: Path, *, result_id: str = "RESULT_1", forbidden: bool = False) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "FX_EXTERNAL_RESEARCH_RESULT_V1",
            "result_id": result_id,
            "hypothesis_id": "HYP_1",
            "instrument": "EUR_USD",
            "result_status": "REJECTED",
            "knowable_at_utc": "2026-10-25T00:00:00Z",
            "safety": {"research_only": True, "downstream_authority": "NONE"},
        }
        if forbidden:
            record["account_id"] = "secret"
        core = {
            "schema": "FX_RESEARCH_RESULT_PAYLOAD_V1",
            "source_system": "TEST",
            "source_repo": "repo",
            "source_commit": "commit",
            "result_records": [record],
            "source_artifacts": [],
            "authority": {"research_only": True, "automatic_promotion": False, "order_authority": False, "downstream_activation": False},
        }
        content_sha = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        package_id = f"FX_RESULT_PACKAGE_{content_sha[:24]}"
        payload = {**core, "package_id": package_id, "content_sha256": content_sha}
        payload_path = root / f"{package_id}.payload.json.gz"
        payload_path.write_bytes(gzip.compress(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
        manifest = {
            "schema": "FX_RESEARCH_RESULT_MANIFEST_V1", "package_id": package_id,
            "created_at_utc": "2026-10-25T00:00:00Z", "source_system": "TEST",
            "source_repo": "repo", "source_commit": "commit", "payload_path": payload_path.name,
            "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(), "content_sha256": content_sha,
            "result_count": 1,
            "authority": {"research_only": True, "automatic_promotion": False, "order_authority": False, "downstream_activation": False},
        }
        manifest_path = root / f"{package_id}.manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_register_is_immutable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._package(Path(directory))
            first = register_package(self.connection, manifest, imported_at_utc="2026-10-25T01:00:00Z")
            second = register_package(self.connection, manifest, imported_at_utc="2026-10-25T02:00:00Z")
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(result_status(self.connection)["result_count"], 1)

    def test_forbidden_account_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._package(Path(directory), forbidden=True)
            with self.assertRaisesRegex(ValueError, "prohibited fields"):
                validate_package(manifest)

    def test_conflicting_result_rewrite_rolls_back_new_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._package(root / "first", result_id="RESULT_1")
            register_package(self.connection, first)
            second_root = root / "second"
            second = self._package(second_root, result_id="RESULT_1")
            payload_path = next(second_root.glob("*.payload.json.gz"))
            with gzip.open(payload_path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            payload["result_records"][0]["result_status"] = "PASS"
            core = {key: value for key, value in payload.items() if key not in {"package_id", "content_sha256"}}
            content_sha = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            package_id = f"FX_RESULT_PACKAGE_{content_sha[:24]}"
            payload.update({"package_id": package_id, "content_sha256": content_sha})
            replacement_payload = second_root / f"{package_id}.payload.json.gz"
            replacement_payload.write_bytes(gzip.compress(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
            manifest = json.loads(second.read_text(encoding="utf-8"))
            manifest.update({
                "package_id": package_id,
                "payload_path": replacement_payload.name,
                "payload_sha256": hashlib.sha256(replacement_payload.read_bytes()).hexdigest(),
                "content_sha256": content_sha,
            })
            replacement_manifest = second_root / f"{package_id}.manifest.json"
            replacement_manifest.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                register_package(self.connection, replacement_manifest)
        manifest_count = self.connection.execute("SELECT COUNT(*) FROM external_result_manifests").fetchone()[0]
        self.assertEqual(manifest_count, 1)

    def test_sync_copies_and_registers_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            self._package(source)
            first = sync_packages(self.connection, source, root / "inbox")
            second = sync_packages(self.connection, source, root / "inbox")
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["unchanged"], 1)


if __name__ == "__main__":
    unittest.main()
