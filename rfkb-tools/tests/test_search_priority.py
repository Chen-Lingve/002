import tempfile
import unittest

from rfkb.store import KnowledgeStore
from tests.helpers import fixture, publish


class SearchPriorityTests(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        self.store = KnowledgeStore(root, test_mode=True)
        self.source, _ = fixture(self.store)

    def item(self, title, summary="", **body):
        return publish(self.store, {
            "kind": "case", "title": title, "summary": summary, "family": "TEST",
            "test_only": True, "body": {"description": "Test evidence", **body},
            "references": [{"record_id": self.source["record_id"], "version": 1,
                            "locator": "Synthetic test evidence"}],
        })

    def test_aliased_title_before_newer_summary_and_body(self):
        title = self.item("三维建模 | 参数与 STEP")
        summary = self.item("Related summary", "Includes 3D建模")
        body = self.item("Related body", notes="Mentions 3D建模")
        hit = self.store.search("3D建模", kind="case", limit=1)
        self.assertEqual(hit["total"], 3)
        self.assertEqual(hit["items"][0]["record_id"], title["record_id"])
        after = self.store.search("3D建模", kind="case", offset=1)
        self.assertEqual([x["record_id"] for x in after["items"]],
                         [body["record_id"], summary["record_id"]])

    def test_normalized_exact_part_number_before_title_and_body(self):
        part = self.item("Legacy connector", part_number="SMA-DEMO047-X-1")
        title = self.item("Overview of SMA-DEMO047-X-1 test fixtures")
        body = self.item("Comparison", notes="SMA-DEMO047-X-1 setup")
        found = self.store.search("sma_demo047-x-1", kind="case")
        self.assertEqual([x["record_id"] for x in found["items"]],
                         [part["record_id"], title["record_id"], body["record_id"]])
        recent = self.store.search(kind="case")
        self.assertEqual([x["record_id"] for x in recent["items"]],
                         [body["record_id"], title["record_id"], part["record_id"]])
