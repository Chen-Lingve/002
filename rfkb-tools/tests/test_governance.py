from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from rfkb.backup import create_backup, restore_backup
from rfkb.web import create_app
from rfkb.store import KnowledgeStore
from tests.helpers import fixture, publish


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.app = create_app(Path(self.temp) / 'db')
        self.store = self.app.state.store
        self.client = self.enterContext(TestClient(self.app))
        self.source, _ = fixture(self.store)

    def record(self, title, body, family='SMA / MCX', kind='case'):
        return dict(kind=kind, title=title, family=family, test_only=True,
                    body=body, references=[dict(record_id=self.source['record_id'],
                                               version=1, locator='Synthetic fixture')])

    def test_query_aliases_and_part_separators_preserve_visibility(self):
        method = publish(self.store, self.record('图纸审阅', {'description': '检查步骤'}))
        draft = self.store.create_record(
            self.record('SMA-DEMO047 焊丝', {'description': '估算'}), 'Author')
        self.store.create_record(self.record('SMPM 焊丝', {'description': '估算'}, 'SMPM'), 'Author')
        self.assertEqual(self.store.search('图纸审查')['total'], 1)
        self.assertEqual(self.store.search('焊锡丝')['total'], 0)
        for query in ('焊锡丝', 'SMA DEMO047', 'SMA_DEMO047', 'SMA－DEMO047'):
            for family in ('sma', 'MCX', 'SMA / MCX'):
                with self.subTest(query=query, family=family):
                    items = self.client.get('/api/records', params=dict(
                        query=query, family=family, include_drafts=True)).json()['items']
                    self.assertEqual([item['record_id'] for item in items], [draft['record_id']])
        self.assertEqual(method['status'], 'published')

    def test_classification_filters_preserve_published_content_hash(self):
        method = publish(self.store, self.record('图纸审阅', {'description': '检查步骤'}))
        self.store.classify_legacy_case(method['record_id'], 1, method['content_hash'], 'general_method')
        self.store.create_record(self.record('历史项目', {'description': '记录', 'case_type': 'project_case'}), 'Author')
        manual = publish(self.store, self.record('人工核对', {
            'operation': 'manual', 'review_instructions': '核对图号。'}, kind='rule'))
        rules = self.store.search(rule_mode='manual')['items']
        self.assertEqual([r['record_id'] for r in rules], [manual['record_id']])
        hits = self.client.get('/api/records', params={'case_type': 'general_method'}).json()['items']
        self.assertEqual([(r['record_id'], r['content_hash']) for r in hits],
                         [(method['record_id'], method['content_hash'])])
        self.assertEqual(hits[0]['body'], method['body'])
        self.assertEqual(self.store.search(case_type='project_case')['total'], 0)
        self.assertEqual(self.store.search(case_type='project_case', include_drafts=True)['total'], 1)
        self.assertEqual(self.client.get('/api/records?case_type=bogus').status_code, 400)

    def test_submission_return_edit_and_backup_preserve_exact_snapshots(self):
        data = self.record('草稿一', {'description': '初稿'})
        first = self.store.create_record(data, 'Author')
        rid = first['record_id']
        second = self.store.save_draft(rid, 1, data | {'title': '送审稿'}, first['edit_token'], 'Author')
        pending = self.store.transition(rid, 1, 'submit', second['edit_token'], 'Author', 'submit')
        returned = self.store.transition(rid, 1, 'return', pending['edit_token'], 'Reviewer', 'revise')
        third = self.store.save_draft(rid, 1, data | {'title': '退回后编辑'}, returned['edit_token'], 'Author')
        for expected in (first, second, third):
            path = f"/api/records/{rid}/versions/1/snapshots/{expected['content_hash']}"
            result = self.client.get(path)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['payload']['title'], expected['title'])
        self.assertEqual(self.client.get(f"/api/records/{rid}/versions/1/snapshots/{'0' * 64}").status_code, 404)
        events = self.client.get(f'/api/records/{rid}/audit').json()['items']
        self.assertEqual([e['content_hash'] for e in events if e['action'] == 'submit'], [second['content_hash']])
        archive = create_backup(self.store, Path(self.temp) / 'after.zip')
        restored = KnowledgeStore(restore_backup(archive, Path(self.temp) / 'restored'))
        self.assertEqual(restored.get_snapshot(rid, 1, second['content_hash'])['payload']['title'], '送审稿')
