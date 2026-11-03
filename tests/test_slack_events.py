"""Tests for the Slack Events API receiver.

Covers the three things that can silently break reply tracking: signature
verification, thread filtering and duplicate delivery.
"""
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main, slack_events, slack_history, storage

SECRET = "test-signing-secret"
CHANNEL = "C_TEST"
PARENT_TS = "1700000000.000100"
BODY_TS = "1700000000.000200"
NOTE_TS = "1700000000.000300"


def signature(secret, timestamp, body: bytes) -> str:
    basestring = b":".join([b"v0", timestamp.encode(), body])
    return "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()


class SignatureTests(unittest.TestCase):
    def test_valid_signature_passes(self):
        body = b'{"a":1}'
        ts = str(int(time.time()))
        slack_events.verify_signature(SECRET, ts, signature(SECRET, ts, body), body)

    def test_missing_secret_is_rejected(self):
        with self.assertRaisesRegex(slack_events.SignatureError, "not configured"):
            slack_events.verify_signature(None, "1", "v0=x", b"{}")

    def test_missing_headers_are_rejected(self):
        for ts, sig in ((None, "v0=x"), ("123", None), (None, None)):
            with self.subTest(ts=ts, sig=sig), self.assertRaises(slack_events.SignatureError):
                slack_events.verify_signature(SECRET, ts, sig, b"{}")

    def test_wrong_signature_is_rejected(self):
        body = b'{"a":1}'
        ts = str(int(time.time()))
        with self.assertRaisesRegex(slack_events.SignatureError, "mismatch"):
            slack_events.verify_signature(SECRET, ts, "v0=" + "0" * 64, body)

    def test_stale_timestamp_is_rejected(self):
        body = b"{}"
        old = str(int(time.time()) - 600)
        with self.assertRaisesRegex(slack_events.SignatureError, "window"):
            slack_events.verify_signature(SECRET, old, signature(SECRET, old, body), body)

    def test_future_timestamp_is_rejected(self):
        body = b"{}"
        future = str(int(time.time()) + 600)
        with self.assertRaisesRegex(slack_events.SignatureError, "window"):
            slack_events.verify_signature(SECRET, future, signature(SECRET, future, body), body)

    def test_malformed_timestamp_is_rejected(self):
        with self.assertRaisesRegex(slack_events.SignatureError, "Malformed"):
            slack_events.verify_signature(SECRET, "not-a-number", "v0=x", b"{}")


class EventsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, 'DB_PATH', Path(self.temp.name) / 'qa.db'))
        self.enterContext(patch('app.local_access.LOCAL_HOSTS', {'127.0.0.1', 'testclient'}))
        self.enterContext(patch.dict('os.environ', {'SLACK_SIGNING_SECRET': SECRET}))
        storage.initialize()
        storage.save_slack_token(storage.LOCAL_USER_ID, 'fake-user-token')
        self.enterContext(patch.object(main, 'get_slack_route', return_value=(CHANNEL, [])))
        self.sender = self.enterContext(patch.object(main, 'post_message', AsyncMock()))
        self.enterContext(patch.object(
            slack_history, 'get_permalink',
            AsyncMock(return_value='https://example.slack.com/archives/C/p1')))
        self.client = self.enterContext(
            TestClient(main.app, base_url='http://127.0.0.1', raise_server_exceptions=False))
        self.task = self.client.post('/api/tasks', json={'jira_id': 'QA-77', 'title': 'Replies'}).json()
        self.set_path = f"/api/tasks/{self.task['id']}/sets"
        self.saved = self.client.post(self.set_path, json={
            'name': 'Run', 'settings': {}, 'region': 'TR', 'mention_users': [],
            'cases': [{'title': 'A', 'text': 'Body A', 'comment': 'More A', 'request_text': 'Req A'}],
        }).json()
        self.case_id = self.saved['cases'][0]['id']
        self.sender.side_effect = [
            {'channel': CHANNEL, 'ts': PARENT_TS},
            {'channel': CHANNEL, 'ts': BODY_TS},
            {'channel': CHANNEL, 'ts': NOTE_TS},
        ]
        self.client.post('/slack/send-cases', json={
            'region': 'TR', 'mention_users': [],
            'cases': [{'case_ids': [self.case_id], 'title': 'A', 'text': 'Body A',
                       'comment': 'More A', 'request_text': 'Req A'}],
        })

    def post_event(self, payload, *, secret=SECRET, ts=None, retry=None):
        body = json.dumps(payload).encode()
        timestamp = ts or str(int(time.time()))
        headers = {
            'x-slack-request-timestamp': timestamp,
            'x-slack-signature': signature(secret, timestamp, body),
        }
        if retry:
            headers['x-slack-retry-num'] = retry
        # Slack posts from its own infrastructure: simulate a public host.
        return self.client.post('/slack/events', content=body, headers=headers)

    def message_event(self, **overrides):
        event = {
            'type': 'message',
            'channel': CHANNEL,
            'thread_ts': PARENT_TS,
            'ts': '1700000000.000400',
            'user': 'U_REAL',
            'text': 'Оплата прошла',
            'client_msg_id': 'cmid-1',
        }
        event.update(overrides)
        return {
            'type': 'event_callback',
            'event_id': 'Ev-1',
            'event': event,
        }

    def replies(self):
        return self.client.get(
            f"{self.set_path}/{self.saved['id']}/cases/{self.case_id}/slack-replies"
        ).json()

    def test_url_verification_returns_challenge(self):
        response = self.post_event({'type': 'url_verification', 'challenge': 'abc123'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'challenge': 'abc123'})

    def test_bad_signature_is_rejected(self):
        response = self.post_event(self.message_event(), secret='wrong-secret')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.replies(), [])

    def test_stale_timestamp_is_rejected(self):
        old = str(int(time.time()) - 3600)
        response = self.post_event(self.message_event(), ts=old)
        self.assertEqual(response.status_code, 401)

    def test_missing_signing_secret_rejects_everything(self):
        with patch.dict('os.environ', {'SLACK_SIGNING_SECRET': ''}):
            self.assertEqual(self.post_event(self.message_event()).status_code, 401)

    def test_reply_in_tracked_thread_is_stored(self):
        response = self.post_event(self.message_event())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'stored')
        stored = self.replies()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]['text'], 'Оплата прошла')
        self.assertEqual(stored[0]['ts'], '1700000000.000400')
        self.assertEqual(stored[0]['thread_ts'], PARENT_TS)

    def test_reply_in_unknown_thread_is_ignored(self):
        response = self.post_event(self.message_event(thread_ts='1700000000.999999'))
        self.assertEqual(response.json()['reason'], 'unknown-thread')
        self.assertEqual(self.replies(), [])

    def test_own_messages_are_skipped_by_ts_not_by_author(self):
        # Exactly what the app posted: the parent, the body and our note.
        for ts in (PARENT_TS, BODY_TS, NOTE_TS):
            with self.subTest(ts=ts):
                response = self.post_event(self.message_event(ts=ts, event_id=f'Ev-{ts}'))
                self.assertEqual(response.json()['reason'], 'own-message')
        self.assertEqual(self.replies(), [])

    def test_same_author_can_answer_later(self):
        # The author of our body message writes a real reply from the same user.
        response = self.post_event(self.message_event(ts='1700000000.000500', user='U_BOT'))
        self.assertEqual(response.json()['status'], 'stored')

    def test_bot_and_subtype_messages_are_ignored(self):
        self.assertEqual(
            self.post_event(self.message_event(bot_id='B1', event_id='Ev-bot')).json()['reason'], 'bot')
        self.assertEqual(
            self.post_event(self.message_event(subtype='message_changed', event_id='Ev-sub')).json()['reason'],
            'subtype')
        self.assertEqual(self.replies(), [])

    def test_root_message_without_thread_ts_is_ignored(self):
        payload = self.message_event()
        payload['event'].pop('thread_ts')
        self.assertEqual(self.post_event(payload).json()['reason'], 'not-a-thread-reply')

    def test_duplicate_event_id_is_processed_once(self):
        first = self.post_event(self.message_event())
        second = self.post_event(self.message_event())
        self.assertEqual(first.json()['status'], 'stored')
        self.assertIn(second.json()['reason'], ('duplicate-event', 'duplicate-reply'))
        self.assertEqual(len(self.replies()), 1)

    def test_slack_retry_is_not_processed_twice(self):
        payload = self.message_event(event_id='Ev-retry')
        self.assertEqual(self.post_event(payload).json()['status'], 'stored')
        retried = self.post_event(payload, retry='1')
        self.assertEqual(retried.json()['reason'], 'retry')
        self.assertEqual(len(self.replies()), 1)

    def test_unsupported_event_type_is_ignored(self):
        payload = self.message_event()
        payload['event']['type'] = 'reaction_added'
        self.assertEqual(self.post_event(payload).json()['reason'], 'unsupported-event')

    def test_invalid_json_returns_400(self):
        body = b'not json'
        timestamp = str(int(time.time()))
        response = self.client.post('/slack/events', content=body, headers={
            'x-slack-request-timestamp': timestamp,
            'x-slack-signature': signature(SECRET, timestamp, body),
        })
        self.assertEqual(response.status_code, 400)

    def test_events_endpoint_is_reachable_through_tunnel(self):
        # Slack posts from its own servers, so the local-access middleware must
        # not block this route.
        body = json.dumps({'type': 'url_verification', 'challenge': 'x'}).encode()
        timestamp = str(int(time.time()))
        response = self.client.post('/slack/events', content=body, headers={
            'host': 'pacifism-vastness-elevation.ngrok-free.dev',
            'x-forwarded-host': 'pacifism-vastness-elevation.ngrok-free.dev',
            'x-slack-request-timestamp': timestamp,
            'x-slack-signature': signature(SECRET, timestamp, body),
        })
        self.assertEqual(response.status_code, 200)

    def test_replies_are_scoped_to_their_case(self):
        # A second *task* is needed: one task owns exactly one editable set, so
        # posting another set would replace the case history.
        other_task = self.client.post('/api/tasks', json={'jira_id': 'QA-88', 'title': 'Other'}).json()
        other_path = f"/api/tasks/{other_task['id']}/sets"
        second = self.client.post(other_path, json={
            'name': 'Run 2', 'settings': {}, 'region': 'TR', 'mention_users': [],
            'cases': [{'title': 'B', 'text': 'Body B', 'comment': '', 'request_text': ''}],
        }).json()
        other_id = second['cases'][0]['id']
        self.assertEqual(self.post_event(self.message_event()).json()['status'], 'stored')
        self.assertEqual(len(self.replies()), 1)
        response = self.client.get(f"{other_path}/{second['id']}/cases/{other_id}/slack-replies")
        self.assertEqual(response.json(), [])


if __name__ == '__main__':
    unittest.main()
