import tempfile
import unittest
from pathlib import Path

from rfkb.demo import initialize
from rfkb.store import KBError, KnowledgeStore
from tests.helpers import fixture, publish


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = KnowledgeStore(self.tmp.name)
        self.source, self.interface = fixture(self.store)
        self.refs = [
            {"record_id": self.source["record_id"], "version": 1, "locator": "Test source page 1"},
            {"record_id": self.interface["record_id"], "version": 1, "locator": "Test profile"}]
        self.profile = {"record_id": self.interface["record_id"], "version": 1}

    def data(self, kind, body):
        return {"kind": kind, "title": "TEST ONLY " + kind, "family": "TEST",
                "test_only": True, "references": self.refs, "body": body}

    def test_selection_template_case_and_exact_profile_links(self):
        selection = publish(self.store, self.data("selection", {
            "profile_ref": self.profile, "parameters": {
                "shaft": {"lower": "9.4", "upper": "9.6", "unit": "mm"},
                "hole": {"value": "10.5", "unit": "mm"}}}))
        template = publish(self.store, self.data("template", {
            "profile_ref": self.profile, "artifact_id": self.source["body"]["artifact_id"],
            "dimension_map": {"shaft": "TEST-D1@TEST-Sketch"}}))
        case = publish(self.store, self.data("case", {"description": "Synthetic observation only."}))
        context = self.store.context({"records": [
            {"record_id": record["record_id"], "version": 1}
            for record in (selection, template, case)]})
        self.assertEqual(len(context["records"]), 5)
        self.assertEqual(self.store.list_artifacts()["total"], 1)

    def test_unknown_template_mapping_and_cross_family_rule_are_rejected(self):
        with self.assertRaises(KBError):
            publish(self.store, self.data("template", {
                "profile_ref": self.profile, "artifact_id": self.source["body"]["artifact_id"],
                "dimension_map": {"unknown": "not-a-real-dimension"}}))
        rule_data = self.data("rule", {"operation": "clearance", "hole": "hole",
                                      "shaft": "shaft", "lower": "0", "unit": "mm"})
        rule_data["family"] = "OTHER-TEST"
        rule = publish(self.store, rule_data)
        with self.assertRaises(KBError):
            self.store.evaluate({
                "profile": self.profile, "parameters": {}, "rules": [
                    {"record_id": rule["record_id"], "version": 1}]})

    def test_retired_source_downgrades_apparent_pass_and_exact_snapshot_remains(self):
        request = {"profile": self.profile, "rules": [], "parameters": {
            "shaft": {"value": "9.5", "unit": "mm"},
            "hole": {"value": "10.5", "unit": "mm"}}}
        original = self.store.evaluate(request)
        self.store.transition(self.source["record_id"], 1, "retire",
                              self.source["edit_token"], "Test reviewer", "Retired synthetic source")
        result = self.store.evaluate(request)
        self.assertEqual(result["outcome"], "insufficient_data")
        self.assertTrue(result["evidence_warnings"])
        self.assertEqual(result["context_hash"], original["context_hash"])
        self.assertEqual(self.store.get_run(original["run_id"])["result"]["outcome"], "pass")
        self.assertEqual(self.store.list_runs()["total"], 2)

    def test_return_from_pending_and_demo_reinitialization_are_explicit(self):
        draft = self.store.new_version(self.source["record_id"], 1, "Test author")
        pending = self.store.transition(draft["record_id"], 2, "submit",
                                        draft["edit_token"], "Test author", "Review")
        returned = self.store.transition(draft["record_id"], 2, "return",
                                         pending["edit_token"], "Test reviewer", "Needs more evidence")
        self.assertEqual(returned["status"], "draft")
        demo_root = Path(self.tmp.name) / "separate-demo"
        info = initialize(demo_root)
        demo = KnowledgeStore(demo_root)
        self.assertTrue(info["test_only"])
        self.assertTrue(demo.stats()["test_mode"])
        self.assertEqual(demo.stats()["records"], 3)
        with self.assertRaises(KBError):
            initialize(demo_root)
