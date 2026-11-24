import importlib
import tempfile
import unittest

from tests.helpers import fixture, publish


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("rfkb"),
                             "Engineering evaluation service has not been implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        module = importlib.import_module("rfkb.store")
        self.store = module.KnowledgeStore(self.tmp.name)
        self.source, self.profile = fixture(self.store)

    def request(self, parameters):
        return {"profile": {"record_id": self.profile["record_id"], "version": 1},
                "parameters": parameters, "rules": []}

    def test_decimal_unit_conversion_and_inclusive_boundaries(self):
        request = self.request({"shaft": {"value": "0.375", "unit": "in"},
                                "hole": {"value": "10.1", "unit": "mm"}})
        result = self.store.evaluate(request)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["checks"][0]["measured"]["lower"], "9.525")
        self.assertTrue(result["test_only"])
        self.assertIn("not", result["limitations"].lower())

    def test_missing_input_or_wrong_unit_cannot_become_pass(self):
        cases = [
            {"shaft": {"value": "9.5", "unit": "mm"}},
            {"shaft": {"value": "9.5", "unit": "kg"},
             "hole": {"value": "10.5", "unit": "mm"}},
            {"shaft": {"value": "NaN", "unit": "mm"},
             "hole": {"value": "10.5", "unit": "mm"}},
        ]
        for parameters in cases:
            with self.subTest(parameters=parameters):
                self.assertEqual(self.store.evaluate(self.request(parameters))["outcome"],
                                 "insufficient_data")

    def test_limit_failure_is_recorded_with_a_pinned_snapshot(self):
        result = self.store.evaluate(self.request({
            "shaft": {"value": "10.01", "unit": "mm"},
            "hole": {"value": "10.5", "unit": "mm"}}))
        self.assertEqual(result["outcome"], "fail")
        snapshot = self.store.get_run(result["run_id"])
        self.assertEqual(snapshot["result"]["outcome"], "fail")
        self.assertEqual(snapshot["context"]["records"][0]["version"], 1)
        self.assertTrue(snapshot["context"]["records"][0]["content_hash"])

    def test_clearance_uses_explicit_manufacturing_intervals(self):
        rule = publish(self.store, {
            "kind": "rule", "title": "TEST ONLY clearance", "family": "TEST",
            "summary": "Synthetic bound, not an engineering requirement.", "test_only": True,
            "references": [{"record_id": self.source["record_id"], "version": 1,
                            "locator": "Synthetic fixture"}],
            "body": {"operation": "clearance", "hole": "hole", "shaft": "shaft",
                     "unit": "mm", "lower": "0.1", "upper": "1.5"},
        })
        request = self.request({
            "shaft": {"lower": "9.4", "upper": "9.6", "unit": "mm"},
            "hole": {"lower": "10.2", "upper": "10.4", "unit": "mm"}})
        request["rules"] = [{"record_id": rule["record_id"], "version": 1}]
        result = self.store.evaluate(request)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["checks"][-1]["measured"], {"lower": "0.6", "upper": "1"})
        request["parameters"]["shaft"] = {"value": "9.5", "unit": "mm"}
        self.assertEqual(self.store.evaluate(request)["outcome"], "insufficient_data")

    def test_read_only_evaluation_does_not_write_a_run(self):
        request = self.request({"shaft": {"value": "9.5", "unit": "mm"},
                                "hole": {"value": "10.5", "unit": "mm"}})
        before = self.store.stats()["runs"]
        result = self.store.evaluate(request, persist=False)
        self.assertNotIn("run_id", result)
        self.assertEqual(self.store.stats()["runs"], before)
