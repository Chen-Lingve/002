import copy
import importlib
import tempfile
import unittest

from tests.helpers import fixture, interface_payload, publish, source_payload


class StoreTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.find_spec("rfkb")
        self.assertIsNotNone(spec, "Versioned knowledge service has not been implemented")
        self.module = importlib.import_module("rfkb.store")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = self.module.KnowledgeStore(self.tmp.name)

    def test_draft_is_editable_but_not_visible_to_default_agent_search(self):
        artifact = self.store.add_artifact("fixture.txt", b"synthetic")
        record = self.store.create_record(source_payload(artifact["artifact_id"]), "Tester")
        self.assertEqual(self.store.search()["total"], 0)
        changed = source_payload(artifact["artifact_id"])
        changed["title"] = "Changed draft"
        saved = self.store.save_draft(record["record_id"], 1, changed,
                                      record["edit_token"], "Tester")
        self.assertEqual(saved["title"], "Changed draft")
        self.assertGreater(saved["edit_token"], record["edit_token"])

    def test_publication_requires_review_and_blocks_content_edits(self):
        source, _ = fixture(self.store)
        with self.assertRaises(self.module.KBError):
            self.store.save_draft(source["record_id"], 1, source,
                                  source["edit_token"], "Tester")
        self.assertEqual(self.store.get_record(source["record_id"])["status"], "published")

    def test_stale_draft_save_cannot_overwrite_the_newer_edit(self):
        artifact = self.store.add_artifact("fixture.txt", b"synthetic")
        payload = source_payload(artifact["artifact_id"])
        record = self.store.create_record(payload, "Tester")
        self.store.save_draft(record["record_id"], 1, payload, record["edit_token"], "Tester")
        with self.assertRaises(self.module.KBError):
            self.store.save_draft(record["record_id"], 1, payload, record["edit_token"], "Tester")

    def test_new_publication_preserves_old_version_and_its_dependents(self):
        source, interface = fixture(self.store)
        v2 = self.store.new_version(source["record_id"], 1, "Tester")
        pending = self.store.transition(source["record_id"], 2, "submit",
                                        v2["edit_token"], "Tester", "New edition")
        new = self.store.transition(source["record_id"], 2, "publish",
                                    pending["edit_token"], "Tester", "Reviewed")
        self.assertEqual(new["version"], 2)
        self.assertEqual(self.store.get_record(source["record_id"])["version"], 2)
        self.assertEqual(self.store.get_record(source["record_id"], 1)["status"], "superseded")
        context = self.store.context({"records": [
            {"record_id": interface["record_id"], "version": 1}]})
        self.assertIn((source["record_id"], 1),
                      [(r["record_id"], r["version"]) for r in context["records"]])
        self.assertEqual(len(self.store.audit(source["record_id"])), 6)

    def test_unreviewed_or_wrong_scope_dependency_cannot_be_published(self):
        artifact = self.store.add_artifact("fixture.txt", b"synthetic")
        source = self.store.create_record(source_payload(artifact["artifact_id"]), "Tester")
        interface = self.store.create_record(interface_payload(source), "Tester")
        pending = self.store.transition(interface["record_id"], 1, "submit",
                                        interface["edit_token"], "Tester", "Review")
        with self.assertRaises(self.module.KBError):
            self.store.transition(interface["record_id"], 1, "publish",
                                  pending["edit_token"], "Tester", "Reviewed")
        source = self.store.transition(source["record_id"], 1, "submit",
                                      source["edit_token"], "Tester", "Review")
        source = self.store.transition(source["record_id"], 1, "publish",
                                      source["edit_token"], "Tester", "Reviewed")
        payload = interface_payload(source)
        payload["test_only"] = False
        draft = self.store.create_record(payload, "Tester")
        pending = self.store.transition(draft["record_id"], 1, "submit",
                                        draft["edit_token"], "Tester", "Review")
        with self.assertRaises(self.module.KBError):
            self.store.transition(draft["record_id"], 1, "publish",
                                  pending["edit_token"], "Tester", "Reviewed")

    def test_invalid_constraint_and_missing_source_block_publication(self):
        source, _ = fixture(self.store)
        for change in ("reversed", "nan", "no_source"):
            payload = interface_payload(source)
            if change == "reversed":
                payload["body"]["constraints"][0]["lower"] = "12"
            elif change == "nan":
                payload["body"]["constraints"][0]["upper"] = "NaN"
            else:
                payload["references"] = []
            draft = self.store.create_record(payload, "Tester")
            pending = self.store.transition(draft["record_id"], 1, "submit",
                                            draft["edit_token"], "Tester", "Review")
            with self.subTest(change=change), self.assertRaises(self.module.KBError):
                self.store.transition(draft["record_id"], 1, "publish",
                                      pending["edit_token"], "Tester", "Reviewed")

    def test_search_filters_keep_roles_families_and_statuses_separate(self):
        source, interface = fixture(self.store)
        other = interface_payload(source)
        other["body"]["role"] = "socket"
        publish(self.store, other)
        results = self.store.search(query="中文", kind="interface", role="pin", family="TEST")
        self.assertEqual(results["total"], 1)
        self.assertEqual(results["items"][0]["record_id"], interface["record_id"])
        self.assertEqual(self.store.search(query='" OR 1=1 --')["total"], 0)
        self.assertEqual(self.store.search(family="SMPM")["total"], 0)

    def test_retired_record_is_hidden_but_explicit_version_is_traceable(self):
        source, _ = fixture(self.store)
        retired = self.store.transition(source["record_id"], 1, "retire",
                                        source["edit_token"], "Tester", "Retired fixture")
        self.assertEqual(retired["status"], "retired")
        self.assertNotIn(source["record_id"],
                         [r["record_id"] for r in self.store.search()["items"]])
        self.assertEqual(self.store.get_record(source["record_id"], 1)["status"], "retired")

    def test_original_artifact_is_content_addressed_and_duplicate_safe(self):
        a = self.store.add_artifact("../../original.txt", b"unmodified synthetic bytes")
        b = self.store.add_artifact("other.txt", b"unmodified synthetic bytes")
        self.assertEqual(a["artifact_id"], b["artifact_id"])
        self.assertEqual(self.store.artifact_bytes(a["artifact_id"]), b"unmodified synthetic bytes")
        self.assertNotIn("..", self.store.get_artifact(a["artifact_id"])["storage_name"])

    def test_source_url_requires_a_real_http_host(self):
        payload = source_payload("")
        payload["body"]["source_url"] = "https:missing-host"
        with self.assertRaises(self.module.KBError):
            publish(self.store, payload)

    def test_selection_cannot_publish_unchecked_or_out_of_range_parameters(self):
        source, interface = fixture(self.store)
        payload = {
            "kind": "selection", "title": "TEST ONLY selection", "family": "TEST",
            "test_only": True,
            "references": [
                {"record_id": source["record_id"], "version": 1, "locator": "Test source"},
                {"record_id": interface["record_id"], "version": 1, "locator": "Test profile"}],
            "body": {"profile_ref": {"record_id": interface["record_id"], "version": 1},
                     "parameters": {"shaft": {"value": "100", "unit": "mm"}}}}
        with self.assertRaises(self.module.KBError):
            publish(self.store, payload)

    def test_test_workspace_cannot_create_real_engineering_records(self):
        module = self.module
        demo = module.KnowledgeStore(self.tmp.name + "/demo", test_mode=True)
        data = source_payload("")
        data["test_only"] = False
        with self.assertRaises(module.KBError):
            demo.create_record(data, "Test author")
