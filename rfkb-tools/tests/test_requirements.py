from copy import deepcopy
from unittest import TestCase

from rfkb.validation import KBError, payload


def case_payload():
    reference = {"record_id": "test-source", "version": 1, "locator": "Test source"}
    return {
        "kind": "case", "title": "TEST ONLY - engineering indicators", "test_only": True,
        "references": [reference],
        "body": {
            "description": "Synthetic acceptance example.",
            "requirements_schema_version": 1,
            "acceptance_requirements": [{
                "id": "vswr", "metric": "VSWR", "category": "acceptance_limit",
                "operator": "<", "value": "1.28", "unit": "1",
                "scope": {"object": "Synthetic device", "assembly": "Synthetic test fixture",
                          "frequency_GHz": {"lower": None, "upper": "26.5",
                                            "upper_inclusive": None, "wording": "Below 26.5 GHz"},
                          "reference_plane": None},
                "source": reference.copy(),
                "verification": {"status": "simulation_only", "summary": "No hardware test"},
            }],
        },
    }


class RequirementTests(TestCase):
    def test_preserves_exclusive_operator_unknown_endpoint_and_legacy_case(self):
        record = case_payload()
        self.assertEqual(payload(record)["body"], record["body"])
        del record["body"]["requirements_schema_version"]
        record["body"]["acceptance_requirements"] = [{"legacy": True}]
        self.assertEqual(payload(record)["body"]["acceptance_requirements"], [{"legacy": True}])

    def test_rejects_invalid_version_category_bounds_and_evidence(self):
        for field, value in (("category", "pass"), ("operator", None),
                             ("value", "NaN"), ("unit", ""), ("id", " ")):
            with self.subTest(field=field):
                record = case_payload()
                record["body"]["acceptance_requirements"][0][field] = value
                with self.assertRaises(KBError):
                    payload(record)
        record = case_payload()
        limit = record["body"]["acceptance_requirements"][0]
        limit["scope"]["frequency_GHz"]["lower"] = "27"
        with self.assertRaises(KBError):
            payload(record)
        limit["scope"]["frequency_GHz"]["lower"] = None
        limit["source"]["version"] = 2
        with self.assertRaises(KBError):
            payload(record)
        limit["source"]["version"] = 1
        record["body"]["requirements_schema_version"] = True
        with self.assertRaises(KBError):
            payload(record)

    def test_unknown_limit_has_no_threshold_and_ids_are_unique(self):
        record = case_payload()
        limit = record["body"]["acceptance_requirements"][0]
        limit["category"] = "unconfirmed"
        limit["verification"]["status"] = "not_verified"
        with self.assertRaises(KBError):
            payload(record)
        limit.update(operator=None, value=None, unit=None)
        self.assertEqual(payload(record)["body"]["acceptance_requirements"][0]["value"], None)
        record["body"]["acceptance_requirements"].append(deepcopy(limit))
        with self.assertRaises(KBError):
            payload(record)
