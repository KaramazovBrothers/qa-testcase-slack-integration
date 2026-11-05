"""A case must arrive with its replies so the UI never flags old ones as new.

The workspace compares a reply's timestamp with the newest reply it already
knew when the set was opened. That baseline can only be correct if the set
payload carries `slack_replies`; without them every stored reply looked fresh
and every case lit up on load or save.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main, storage


class SetRepliesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(storage, 'DB_PATH', Path(self.temp.name) / 'data' / 'qa_tests.db')
        self.db_patch.start()
        self.peer = patch('app.local_access.LOCAL_HOSTS', {'localhost', '127.0.0.1', '::1', 'testclient'})
        self.peer.start()
        self.client = TestClient(main.app, base_url='http://127.0.0.1:8000')
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.peer.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def _task_with_set(self):
        task = self.client.post('/api/tasks', json={'jira_id': 'QA-2', 'title': 'T'}).json()['id']
        saved = self.client.post(f'/api/tasks/{task}/sets', json={
            'name': 'S', 'region': 'TR', 'operation': 'deposit', 'mention_users': [],
            'settings': {'fields': {'region': 'TR', 'integration': 'HPP'}},
            'cases': [{'title': 'A', 'text': 'x', 'comment': '', 'request_text': ''}],
        }).json()
        return task, saved

    def test_set_payload_has_empty_replies_for_a_new_case(self):
        task, saved = self._task_with_set()
        case = self.client.get(f"/api/tasks/{task}/sets/{saved['id']}").json()['cases'][0]
        self.assertIn('slack_replies', case)
        self.assertEqual(case['slack_replies'], [])

    def test_set_payload_returns_stored_replies(self):
        task, saved = self._task_with_set()
        case_id = saved['cases'][0]['id']
        with storage.connection() as db:
            send_id = db.execute(
                "INSERT INTO slack_sends(owner_user_id,channel,ts,sent_at,thread_ts,own_ts)"
                " VALUES(?,?,?,?,?,?)",
                (storage.LOCAL_USER_ID, 'C1', '1.2', '2026-01-01T00:00:00+00:00', '1.1', '["1.1","1.2"]'),
            ).lastrowid
            db.execute('INSERT INTO slack_send_cases(send_id,case_id) VALUES(?,?)', (send_id, case_id))
            db.execute(
                "INSERT INTO slack_replies(send_id,channel,thread_ts,ts,author_id,text,received_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (send_id, 'C1', '1.1', '1.3', 'U_HUMAN', 'Ответ', '2026-01-01T00:00:05+00:00'),
            )
        case = self.client.get(f"/api/tasks/{task}/sets/{saved['id']}").json()['cases'][0]
        self.assertEqual(len(case['slack_replies']), 1)
        self.assertEqual(case['slack_replies'][0]['text'], 'Ответ')
        self.assertEqual(case['slack_replies'][0]['ts'], '1.3')


if __name__ == '__main__':
    unittest.main()
