import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from rfkb.store import KBError, KnowledgeStore
from tests.helpers import fixture


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("rfkb.backup"),
                             "Backup/recovery boundary has not been implemented")
        self.backup = importlib.import_module("rfkb.backup")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = KnowledgeStore(self.root / "original")
        self.source, self.profile = fixture(self.store)

    def test_restore_preserves_exact_version_queries_and_original_artifacts(self):
        archive = self.backup.create_backup(self.store, self.root / "backup.zip")
        restored_path = self.backup.restore_backup(archive, self.root / "restored")
        restored = KnowledgeStore(restored_path)
        self.assertEqual(restored.get_record(self.profile["record_id"], 1)["content_hash"],
                         self.profile["content_hash"])
        self.assertEqual(restored.search(query="中文")["total"], 1)
        artifact_id = self.source["body"]["artifact_id"]
        self.assertEqual(restored.artifact_bytes(artifact_id),
                         b"TEST ONLY: no engineering standard.")
        self.assertEqual(restored.evaluate({
            "profile": {"record_id": self.profile["record_id"], "version": 1},
            "parameters": {"shaft": {"value": "9.5", "unit": "mm"},
                           "hole": {"value": "10.5", "unit": "mm"}}, "rules": []},
            persist=False)["outcome"], "pass")

    def test_restore_rejects_existing_target_and_checksum_tampering(self):
        archive = self.backup.create_backup(self.store, self.root / "backup.zip")
        with self.assertRaises(KBError):
            self.backup.restore_backup(archive, self.store.root)
        corrupt = self.root / "corrupt.zip"
        with ZipFile(archive) as src, ZipFile(corrupt, "w") as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                dst.writestr(info.filename, b"changed" if info.filename.startswith("artifacts/") else data)
        with self.assertRaises(KBError):
            self.backup.restore_backup(corrupt, self.root / "rejected")
        self.assertFalse((self.root / "rejected").exists())

    def test_restore_rejects_zip_member_traversal(self):
        archive = self.root / "traversal.zip"
        with ZipFile(archive, "w") as dst:
            dst.writestr("../outside.txt", b"escape")
            dst.writestr("manifest.json", json.dumps({"schema_version": 1, "files": {}}))
        with self.assertRaises(KBError):
            self.backup.restore_backup(archive, self.root / "rejected")
        self.assertFalse((self.root / "outside.txt").exists())
