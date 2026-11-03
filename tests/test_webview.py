"""WebView APK library and the per-channel request list."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from app import main, storage, webview_apk


class WebviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'data' / 'qa_tests.db'
        self.db_patch = patch.object(storage, 'DB_PATH', self.path)
        self.db_patch.start()
        storage.initialize()
        storage.save_slack_token(storage.LOCAL_USER_ID, 'fake-user-token')
        # Never touch the real Slack workspace from a test.
        self.sender = AsyncMock(return_value={'ok': True, 'ts': '1700000000.000001'})
        # The WebView router imports the client directly, not through main.
        self.send_patch = patch('app.webview_api.post_message', self.sender)
        self.send_patch.start()
        self.client = TestClient(main.app, base_url='http://127.0.0.1:8000')
        self.peer_patch = patch(
            'app.local_access.LOCAL_HOSTS', {'localhost', '127.0.0.1', '::1', 'testclient'}
        )
        self.peer_patch.start()
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.peer_patch.stop()
        self.send_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def upload(self, licence='pinco', payload=b'APKDATA', name='build.apk'):
        return self.client.post(
            '/api/webview/apks',
            data={'licence': licence},
            files={'file': (name, io.BytesIO(payload), 'application/vnd.android.package-archive')},
        )

    def test_every_licence_is_listed_even_before_upload(self):
        rows = self.client.get('/api/webview/apks').json()['licences']
        self.assertEqual([r['licence'] for r in rows], list(webview_apk.LICENCES))
        self.assertTrue(all(r['uploaded_at'] is None for r in rows))

    def test_upload_stores_the_file_and_its_date(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['size_bytes'], 7)
        row = next(r for r in self.client.get('/api/webview/apks').json()['licences']
                   if r['licence'] == 'pinco')
        self.assertEqual(row['filename'], 'build.apk')
        self.assertTrue(row['uploaded_at'])

    def test_upload_replaces_the_previous_build(self):
        self.upload(payload=b'OLD')
        self.upload(payload=b'NEWBUILD', name='new.apk')
        rows = self.client.get('/api/webview/apks').json()['licences']
        self.assertEqual(len([r for r in rows if r['licence'] == 'pinco']), 1)
        self.assertEqual(self.client.get('/api/webview/apks/pinco').content, b'NEWBUILD')

    def test_download_returns_the_bytes(self):
        self.upload(payload=b'PAYLOAD123')
        response = self.client.get('/api/webview/apks/pinco')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'PAYLOAD123')
        self.assertIn('attachment', response.headers['content-disposition'])

    def test_download_unknown_licence_is_404(self):
        self.assertEqual(self.client.get('/api/webview/apks/com').status_code, 404)

    def test_unknown_licence_is_rejected(self):
        self.assertEqual(self.upload(licence='nope').status_code, 422)

    def test_empty_file_is_rejected(self):
        self.assertEqual(self.upload(payload=b'').status_code, 422)

    def test_delete_removes_the_build(self):
        self.upload()
        self.assertEqual(self.client.delete('/api/webview/apks/pinco').status_code, 204)
        self.assertEqual(self.client.get('/api/webview/apks/pinco').status_code, 404)

    def test_default_person_is_in_the_channel_list(self):
        people = self.client.get('/api/webview/people').json()['people']
        self.assertIn({'id': 'U03V08KDU31', 'name': 'Denys Denysenko'}, people)

    def test_add_and_remove_a_channel_person(self):
        added = self.client.post('/api/webview/people',
                                 json={'entry': 'https://hglobal.enterprise.slack.com/team/U04BNNL48KF',
                                       'name': 'Tester'})
        self.assertEqual(added.status_code, 201, added.text)
        self.assertEqual(added.json()['id'], 'U04BNNL48KF')
        people = self.client.get('/api/webview/people').json()['people']
        self.assertTrue(any(p['id'] == 'U04BNNL48KF' for p in people))
        self.assertEqual(self.client.delete('/api/webview/people/U04BNNL48KF').status_code, 204)
        self.assertFalse(any(p['id'] == 'U04BNNL48KF'
                             for p in self.client.get('/api/webview/people').json()['people']))

    def test_request_posts_one_message_per_licence_with_the_tag(self):
        response = self.client.post('/api/webview/request', json={'licences': ['pinco', 'com']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.sender.await_count, 2)
        texts = [call.args[2] for call in self.sender.call_args_list]
        self.assertIn('<@U03V08KDU31>', texts[0])
        self.assertIn('Привет! Скинь, пожалуйста, свежую сборку ПРОД для pinco', texts[0])
        self.assertIn('для com', texts[1])
        self.assertEqual(response.json()['channel'], 'C07RKCUN132')

    def test_request_rejects_unknown_licence(self):
        response = self.client.post('/api/webview/request', json={'licences': ['nope']})
        self.assertEqual(response.status_code, 422)
        self.sender.assert_not_awaited()

    def test_request_needs_at_least_one_licence(self):
        self.assertEqual(self.client.post('/api/webview/request', json={'licences': []}).status_code, 422)

    def test_request_is_not_reachable_through_the_tunnel(self):
        forwarded = self.client.post(
            '/api/webview/request', json={'licences': ['pinco']},
            headers={'x-forwarded-for': '1.2.3.4'})
        self.assertIn(forwarded.status_code, (401, 403))
        self.sender.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
