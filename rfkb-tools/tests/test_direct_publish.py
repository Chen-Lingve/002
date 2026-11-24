from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from rfkb.web import create_app
from tests.helpers import interface_payload, source_payload


class DirectPublishTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        app = create_app(Path(folder) / "db")
        self.client = self.enterContext(TestClient(app))
        self.store = app.state.store
        evidence = self.store.add_artifact("synthetic.txt", b"TEST ONLY")
        self.source = source_payload(evidence["artifact_id"])

    def add(self, data, **options):
        return self.client.post("/api/records", json={"record": data, "actor": "Operator", **options})

    def transition(self, record, action, note=""):
        return self.client.post(f"/api/records/{record['record_id']}/transition", json={
            "version": record["version"], "edit_token": record["edit_token"],
            "action": action, "actor": "Operator", "note": note})

    def test_new_record_can_validate_and_publish_without_human_review(self):
        result = self.add(self.source, publish=True)
        self.assertEqual(result.status_code, 200, result.text)
        r = result.json()
        self.assertEqual(r["status"], "published")
        self.assertIsNone(r["reviewed_by"])
        self.assertIsNone(r["review_note"])
        events = self.store.audit(r["record_id"])
        self.assertEqual([e["action"] for e in events], ["create", "validate_publish"])
        self.assertEqual(events[-1]["actor"], "Operator")
        self.assertEqual(events[-1]["content_hash"], r["content_hash"])
        self.assertEqual(self.store.search()["total"], 1)

    def test_existing_pending_and_draft_can_publish_in_one_operation(self):
        draft = self.add(self.source).json()
        pending = self.transition(draft, "submit").json()
        self.assertEqual(self.transition(draft, "validate_publish").status_code, 409)
        self.assertEqual(self.transition(pending, "validate_publish").json().get("status"), "published")
        r = self.add(interface_payload(pending)).json()
        result = self.transition(r, "validate_publish")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "published")
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM dependencies").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM constraints_index").fetchone()[0], 2)

    def test_invalid_create_and_invalid_edit_do_not_commit_any_changes(self):
        broken = deepcopy(self.source)
        broken["body"]["artifact_id"] = "f" * 64
        result = self.add(broken, publish=True)
        self.assertEqual(result.status_code, 404, result.text)
        self.assertEqual(self.store.stats()["records"], 0)
        old = self.add(self.source, publish=True).json()
        rid = old["record_id"]
        rev = self.store.new_version(rid, 1, "Operator")
        url = f"/api/records/{rid}/versions/2"
        result = self.client.put(url, json={"record": broken, "actor": "Operator",
                                            "edit_token": rev["edit_token"], "publish": True})
        self.assertEqual(result.status_code, 404, result.text)
        self.assertEqual(self.store.get_record(rid, 2), rev)
        self.assertEqual(self.store.get_record(rid), old)
        self.assertEqual([e["action"] for e in self.store.audit(rid)],
                         ["create", "validate_publish", "new_version"])
        result = self.client.put(url, json={"record": self.source | {"title": "New title"}, "actor": "Operator",
                                            "edit_token": rev["edit_token"], "publish": True})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "published")
        self.assertEqual(self.store.get_record(rid, 1)["status"], "superseded")
        self.assertEqual(self.store.get_record(rid)["title"], "New title")

    def test_unpublished_dependency_blocks_direct_publication(self):
        draft_source = self.add(self.source).json()
        profile = self.add(interface_payload(draft_source)).json()
        failed = self.transition(profile, "validate_publish")
        self.assertEqual(failed.status_code, 400, failed.text)
        self.assertEqual(self.store.get_record(profile["record_id"], 1), profile)
        self.assertEqual(self.store.search()["total"], 0)
