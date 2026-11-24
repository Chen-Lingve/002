import importlib
import tempfile
import unittest

from fastapi.testclient import TestClient
from tests.helpers import fixture, source_payload


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("rfkb.web"),
                             "HTTP knowledge boundary has not been implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        web = importlib.import_module("rfkb.web")
        self.app = web.create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_empty_production_store_is_not_auto_populated(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        stats = self.client.get("/api/stats").json()
        self.assertEqual(stats["records"], 0)
        self.assertFalse(stats["test_mode"])

    def test_upload_create_edit_submit_publish_and_download_are_real(self):
        uploaded = self.client.post("/api/artifacts", files={
            "file": ("test.txt", b"synthetic original", "text/plain")})
        self.assertEqual(uploaded.status_code, 200)
        artifact = uploaded.json()
        record = self.client.post("/api/records", json={
            "record": source_payload(artifact["artifact_id"]), "actor": "Test user"}).json()
        rid = record["record_id"]
        self.assertEqual(self.client.get("/api/records").json()["total"], 0)
        pending = self.client.post(f"/api/records/{rid}/transition", json={
            "version": 1, "action": "submit", "edit_token": record["edit_token"],
            "actor": "Test user", "note": "Review synthetic input"}).json()
        rejected = self.client.post(f"/api/records/{rid}/transition", json={
            "version": 1, "action": "publish", "edit_token": pending["edit_token"],
            "actor": "Test reviewer", "note": ""})
        self.assertEqual(rejected.status_code, 400)
        published = self.client.post(f"/api/records/{rid}/transition", json={
            "version": 1, "action": "publish", "edit_token": pending["edit_token"],
            "actor": "Test reviewer", "note": "Synthetic content reviewed"})
        self.assertEqual(published.status_code, 200)
        self.assertEqual(self.client.get("/api/records").json()["total"], 1)
        downloaded = self.client.get(f"/api/artifacts/{artifact['artifact_id']}")
        self.assertEqual(downloaded.content, b"synthetic original")
        self.assertIn("attachment", downloaded.headers["content-disposition"])

    def test_preview_is_read_only_and_does_not_serve_active_uploads(self):
        store = self.app.state.store
        cases = [
            ("report.md", b"\xef\xbb\xbf# Report\n<script>alert(1)</script>", 200, "text/plain",
             b"# Report\n<script>alert(1)</script>"),
            ("plot.png", b"\x89PNG\r\n\x1a\nsynthetic", 200, "image/png",
             b"\x89PNG\r\n\x1a\nsynthetic"),
            ("report.pdf", b"%PDF-1.4\nsynthetic", 200, "application/pdf",
             b"%PDF-1.4\nsynthetic"),
            ("fake.png", b"<html>Not a PNG</html>", 415, None, None),
            ("drawing.dwg", b"AC1032", 415, None, None),
            ("unsafe.html", b"<script>alert(2)</script>", 415, None, None),
            ("binary.csv", b"\x00field,data", 415, None, None),
        ]
        for filename, data, status, media_type, expected in cases:
            with self.subTest(filename=filename):
                item = store.add_artifact(filename, data)
                url = f"/api/artifacts/{item['artifact_id']}"
                preview = self.client.get(url + "/preview")
                self.assertEqual(preview.status_code, status)
                if status == 200:
                    self.assertTrue(preview.headers["content-type"].startswith(media_type))
                    self.assertEqual(preview.headers["x-content-type-options"], "nosniff")
                    self.assertEqual(preview.content, expected)
                download = self.client.get(url)
                self.assertEqual(download.content, data)
                self.assertIn("attachment", download.headers["content-disposition"])
        self.assertEqual(self.client.get("/api/artifacts/not-found/preview").status_code, 404)

    def test_cross_origin_mutation_and_missing_actor_are_rejected(self):
        response = self.client.post("/api/records", json={}, headers={"Origin": "https://other.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post("/api/records", json={}).status_code, 422)

    def test_evaluation_run_and_context_are_retrievable_by_exact_versions(self):
        _, interface = fixture(self.app.state.store)
        request = {
            "profile": {"record_id": interface["record_id"], "version": 1},
            "parameters": {"shaft": {"value": "9.5", "unit": "mm"},
                           "hole": {"value": "10.5", "unit": "mm"}}, "rules": []}
        result = self.client.post("/api/evaluate", json=request)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["outcome"], "pass")
        run = self.client.get("/api/runs/" + result.json()["run_id"]).json()
        self.assertEqual(run["context"]["records"][0]["record_id"], interface["record_id"])
        context = self.client.post("/api/context", json={"records": [request["profile"]]}).json()
        self.assertEqual(context["context_hash"], run["context"]["context_hash"])
        self.assertEqual(self.client.get("/api/runs").json()["items"][0]["run_id"], result.json()["run_id"])

    def test_backup_download_is_available_and_path_traversal_is_rejected(self):
        response = self.client.post("/api/backup")
        self.assertEqual(response.status_code, 200)
        name = response.json()["name"]
        self.assertEqual(self.client.get("/api/backups/" + name).status_code, 200)
        self.assertEqual(self.client.get("/api/backups/not-a-backup").status_code, 404)

    def test_malformed_nested_input_returns_domain_error_not_server_crash(self):
        for request in [
            {"profile": {}, "parameters": {}, "rules": {}},
            {"profile": {"record_id": [], "version": 1}, "parameters": {}},
        ]:
            self.assertEqual(self.client.post("/api/evaluate", json=request).status_code, 400)
