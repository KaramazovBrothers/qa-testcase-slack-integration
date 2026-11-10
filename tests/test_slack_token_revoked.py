"""A token Slack refused must be forgotten, not retried on every message.

The user token can be revoked from the Slack UI or by reinstalling the app.
Until now every send failed with the same opaque error and the stored token
stayed forever; the workspace kept claiming "Slack подключён".
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main, slack_client, storage
from app.current_user import get_current_user_id


class RejectedTokenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        storage.initialize()
        self.enterContext(patch("app.local_access.LOCAL_HOSTS", {"127.0.0.1", "testclient"}))
        self.client = self.enterContext(
            TestClient(main.app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
        )
        main.app.dependency_overrides[get_current_user_id] = lambda: storage.LOCAL_USER_ID
        self.addCleanup(main.app.dependency_overrides.clear)
        storage.save_slack_token(storage.LOCAL_USER_ID, "xoxp-old-token",
                                 slack_user_id="U1", team_id="T1", scopes="chat:write")
        self.enterContext(patch.dict("os.environ", {"SLACK_CHANNEL_ID": "C1"}))

    def _send_with(self, error):
        async def refused(*args, **kwargs):
            raise slack_client.token_rejected(error)
        with patch.object(main, "post_message", side_effect=refused):
            return self.client.post("/slack/send", data={"text": "hi"})

    def test_revoked_token_answers_reconnect_and_is_dropped(self):
        response = self._send_with("token_revoked")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.json()["reconnect"])
        self.assertEqual(response.json()["error"], "token_revoked")
        # The dead token is gone, so the UI stops claiming "connected".
        self.assertFalse(self.client.get("/api/slack-status").json()["connected"])
        self.assertEqual(storage.get_slack_identity(storage.LOCAL_USER_ID)["slack_user_id"], "U1")

    def test_each_reconnect_error_is_treated_as_refusal(self):
        for error in ("token_expired", "invalid_auth", "not_authed", "account_inactive"):
            with self.subTest(error=error):
                storage.save_slack_token(storage.LOCAL_USER_ID, "xoxp-old-token")
                response = self._send_with(error)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["error"], error)

    def test_ordinary_failure_is_not_a_reconnect(self):
        async def channelless(*args, **kwargs):
            raise RuntimeError("Slack API failed: channel_not_found")
        with patch.object(main, "post_message", side_effect=channelless):
            response = self.client.post("/slack/send", data={"text": "hi"})
        self.assertNotEqual(response.status_code, 401)
        # A working token must survive unrelated failures.
        self.assertTrue(self.client.get("/api/slack-status").json()["connected"])


if __name__ == "__main__":
    unittest.main()
