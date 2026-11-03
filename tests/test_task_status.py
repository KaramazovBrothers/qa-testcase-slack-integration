"""Task status: every task is active or done, and the sidebar can hide done ones."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import main, storage


class TaskStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'data' / 'qa_tests.db'
        self.db_patch = patch.object(storage, 'DB_PATH', self.path)
        self.db_patch.start()
        self.client = TestClient(main.app, base_url='http://127.0.0.1:8000')
        self.peer_patch = patch(
            'app.local_access.LOCAL_HOSTS', {'localhost', '127.0.0.1', '::1', 'testclient'}
        )
        self.peer_patch.start()
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.peer_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def create(self, jira):
        response = self.client.post('/api/tasks', json={'jira_id': jira, 'title': jira})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_new_task_is_active(self):
        task = self.create('QA-1')
        self.assertEqual(task['status'], 'active')

    def test_toggle_flips_between_active_and_done(self):
        task = self.create('QA-2')
        first = self.client.post(f"/api/tasks/{task['id']}/status")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['status'], 'done')
        second = self.client.post(f"/api/tasks/{task['id']}/status")
        self.assertEqual(second.json()['status'], 'active')

    def test_active_filter_hides_done_tasks(self):
        keep = self.create('QA-3')
        drop = self.create('QA-4')
        self.client.post(f"/api/tasks/{drop['id']}/status")

        every = [t['id'] for t in self.client.get('/api/tasks').json()]
        self.assertEqual(sorted(every), sorted([keep['id'], drop['id']]))

        active = [t['id'] for t in self.client.get('/api/tasks?active=true').json()]
        self.assertEqual(active, [keep['id']])

    def test_active_filter_combines_with_search(self):
        keep = self.create('QA-5')
        self.client.post(f"/api/tasks/{self.create('QA-6')['id']}/status")
        matches = [t['id'] for t in self.client.get('/api/tasks?q=QA-5&active=true').json()]
        self.assertEqual(matches, [keep['id']])
        self.assertEqual(self.client.get('/api/tasks?q=QA-6&active=true').json(), [])

    def test_status_survives_a_save(self):
        task = self.create('QA-7')
        self.client.post(f"/api/tasks/{task['id']}/status")
        response = self.client.put(
            f"/api/tasks/{task['id']}", json={'jira_id': 'QA-7', 'title': 'Renamed'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'done')

    def test_unknown_status_is_rejected(self):
        task = self.create('QA-8')
        response = self.client.put(
            f"/api/tasks/{task['id']}",
            json={'jira_id': 'QA-8', 'title': 'x', 'status': 'archived'},
        )
        self.assertEqual(response.status_code, 422)

    def test_toggle_requires_an_existing_task(self):
        self.assertEqual(self.client.post('/api/tasks/999/status').status_code, 404)


if __name__ == '__main__':
    unittest.main()
