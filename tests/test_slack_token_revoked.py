"""A token Slack refuses must be dropped, so the UI asks to reconnect.

The send path is `/slack/send-cases`: it is the only way a message reaches
Slack now that the legacy `/slack/send` endpoint is gone.
"""

import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main, slack_client, storage
from app.current_user import get_current_user_id


_JIRA_SEQ = itertools.count(1)


class SlackTokenRevokedTests(unittest.TestCase):
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
        # The region must have an explicit route: the app no longer falls back
        # to an environment channel.
        self.enterContext(patch.object(main, "get_slack_route", return_value=("C1", [])))

    def _send_with(self, error):
        async def refused(*args, **kwargs):
            raise slack_client.token_rejected(error)

        jira_id = f"QA-REVOKED-{next(_JIRA_SEQ)}"
        task = self.client.post("/api/tasks", json={"jira_id": jira_id, "title": "t"})
        self.assertEqual(task.status_code, 201, task.text)
        body = {
            "region": "TR",
            "operation": "deposit",
            "mention_users": [],
            "cases": [{
                "case_ids": [1],
                "title": "c",
                "text": "body",
            }],
        }
        with patch.object(main, "post_message", side_effect=refused), \
                patch.object(main.slack_history, "validate_case_ids", return_value=None):
            return self.client.post("/slack/send-cases", json=body)

    def test_revoked_token_answers_reconnect_and_is_dropped(self):
        response = self._send_with("token_revoked")
        self.assertEqual(response.status_code, 401, response.text)
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
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(response.json()["error"], error)

    def test_ordinary_failure_is_not_a_reconnect(self):
        async def channelless(*args, **kwargs):
            raise RuntimeError("Slack API failed: channel_not_found")

        jira_id = f"QA-REVOKED-{next(_JIRA_SEQ)}"
        task = self.client.post("/api/tasks", json={"jira_id": jira_id, "title": "t"})
        self.assertEqual(task.status_code, 201, task.text)
        body = {
            "region": "TR",
            "operation": "deposit",
            "mention_users": [],
            "cases": [{"case_ids": [1], "title": "c", "text": "body"}],
        }
        with patch.object(main, "post_message", side_effect=channelless), \
                patch.object(main.slack_history, "validate_case_ids", return_value=None):
            response = self.client.post("/slack/send-cases", json=body)
        self.assertNotEqual(response.status_code, 401)
        # A working token must survive unrelated failures.
        self.assertTrue(self.client.get("/api/slack-status").json()["connected"])


if __name__ == "__main__":
    unittest.main()
