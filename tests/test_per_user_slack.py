"""Per-user Slack OAuth: separate tokens, separate state, separate data.

The product is multi-user, so one person authorizing Slack must never let a
second person act as them, and an OAuth callback must only ever bind a token
to the user who started that flow.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main, slack_oauth_state_migration, storage


class PerUserTokenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "qa.db"
        self.enterContext(patch.object(storage, "DB_PATH", self.path))
        self.enterContext(patch("app.local_access.LOCAL_HOSTS", {"127.0.0.1", "testclient"}))
        storage.initialize()
        with storage.connection() as db:
            db.execute(
                "INSERT INTO users(id,auth_provider,auth_subject,display_name,created_at,updated_at)"
                " VALUES(2,'test','user-two','Second QA','now','now')"
            )

    def test_tokens_are_stored_per_user(self):
        storage.save_slack_token(1, "token-one", slack_user_id="U_ONE")
        storage.save_slack_token(2, "token-two", slack_user_id="U_TWO")

        self.assertEqual(storage.get_slack_token(1), "token-one")
        self.assertEqual(storage.get_slack_token(2), "token-two")
        self.assertEqual(storage.get_slack_identity(1)["slack_user_id"], "U_ONE")
        self.assertEqual(storage.get_slack_identity(2)["slack_user_id"], "U_TWO")

    def test_one_user_clearing_does_not_affect_the_other(self):
        storage.save_slack_token(1, "token-one")
        storage.save_slack_token(2, "token-two")

        storage.clear_slack_token(1)

        self.assertIsNone(storage.get_slack_token(1))
        self.assertEqual(storage.get_slack_token(2), "token-two")

    def test_user_without_token_has_none(self):
        storage.save_slack_token(1, "token-one")
        self.assertIsNone(storage.get_slack_token(2))
        self.assertFalse(storage.get_slack_identity(2)["connected"])

    def test_identity_reports_recorded_scopes(self):
        storage.save_slack_token(
            1, "tok", slack_user_id="U1", team_id="T1",
            scopes="chat:write,channels:history",
        )
        identity = storage.get_slack_identity(1)
        self.assertTrue(identity["connected"])
        self.assertEqual(identity["team_id"], "T1")
        self.assertEqual(identity["scopes"], ["chat:write", "channels:history"])
        self.assertIsNotNone(identity["issued_at"])

    def test_state_is_bound_to_the_user_who_started_it(self):
        slack_oauth_state_migration.issue_state(self.path, 2, "state-for-two")
        self.assertEqual(slack_oauth_state_migration.consume_state(self.path, "state-for-two"), 2)

    def test_state_is_single_use(self):
        slack_oauth_state_migration.issue_state(self.path, 1, "once")
        self.assertEqual(slack_oauth_state_migration.consume_state(self.path, "once"), 1)
        self.assertIsNone(slack_oauth_state_migration.consume_state(self.path, "once"))

    def test_unknown_state_is_rejected(self):
        self.assertIsNone(slack_oauth_state_migration.consume_state(self.path, "never-issued"))

    def test_expired_state_is_rejected(self):
        slack_oauth_state_migration.issue_state(self.path, 1, "stale")
        with storage.connection() as db:
            db.execute(
                "UPDATE slack_oauth_states SET expires_at='2000-01-01T00:00:00+00:00' WHERE state=?",
                ("stale",),
            )
        self.assertIsNone(slack_oauth_state_migration.consume_state(self.path, "stale"))

    def test_states_do_not_leak_between_users(self):
        slack_oauth_state_migration.issue_state(self.path, 1, "a")
        slack_oauth_state_migration.issue_state(self.path, 2, "b")
        self.assertEqual(slack_oauth_state_migration.consume_state(self.path, "a"), 1)
        self.assertEqual(slack_oauth_state_migration.consume_state(self.path, "b"), 2)


class PerUserCallbackTests(unittest.TestCase):
    """The callback binds the token to the user recorded against the state."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "qa.db"
        self.enterContext(patch.object(storage, "DB_PATH", self.path))
        self.enterContext(patch("app.local_access.LOCAL_HOSTS", {"127.0.0.1", "testclient"}))
        storage.initialize()
        with storage.connection() as db:
            db.execute(
                "INSERT INTO users(id,auth_provider,auth_subject,display_name,created_at,updated_at)"
                " VALUES(2,'test','user-two','Second QA','now','now')"
            )
        self.client = self.enterContext(
            TestClient(main.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        )

    def _exchange(self, token, slack_user_id):
        return AsyncMock(return_value={
            "authed_user": {"access_token": token, "id": slack_user_id},
            "team": {"id": "T_SHARED"},
            "scope": "chat:write",
        })

    def test_callback_writes_the_token_to_the_state_owner(self):
        slack_oauth_state_migration.issue_state(self.path, 2, "for-two")
        with patch.object(main, "exchange_code", self._exchange("tok-two", "U_TWO")):
            response = self.client.get("/slack/oauth/callback?state=for-two&code=c")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(storage.get_slack_token(2), "tok-two")
        self.assertIsNone(storage.get_slack_token(1))

    def test_two_users_get_two_independent_tokens(self):
        slack_oauth_state_migration.issue_state(self.path, 1, "s1")
        with patch.object(main, "exchange_code", self._exchange("tok-one", "U_ONE")):
            self.client.get("/slack/oauth/callback?state=s1&code=c1")

        slack_oauth_state_migration.issue_state(self.path, 2, "s2")
        with patch.object(main, "exchange_code", self._exchange("tok-two", "U_TWO")):
            self.client.get("/slack/oauth/callback?state=s2&code=c2")

        self.assertEqual(storage.get_slack_token(1), "tok-one")
        self.assertEqual(storage.get_slack_token(2), "tok-two")

    def test_replayed_callback_cannot_rebind(self):
        slack_oauth_state_migration.issue_state(self.path, 1, "replay")
        with patch.object(main, "exchange_code", self._exchange("tok-one", "U_ONE")):
            self.assertEqual(
                self.client.get("/slack/oauth/callback?state=replay&code=c").status_code, 200
            )
            started = AsyncMock()
            with patch.object(main, "exchange_code", started):
                self.assertEqual(
                    self.client.get("/slack/oauth/callback?state=replay&code=c").status_code, 400
                )
            started.assert_not_awaited()

    def test_callback_with_foreign_state_does_not_pick_a_user(self):
        with patch.object(main, "exchange_code", self._exchange("tok", "U")):
            response = self.client.get("/slack/oauth/callback?state=invented&code=c")
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(storage.get_slack_token(1))
        self.assertIsNone(storage.get_slack_token(2))

    def test_status_reflects_the_calling_user_only(self):
        storage.save_slack_token(1, "tok-one")
        # The local installation always resolves to user 1, so the endpoint
        # must report connected; user 2 has nothing of their own.
        self.assertTrue(self.client.get("/api/slack-status").json()["connected"])
        self.assertIsNone(storage.get_slack_token(2))


class TokenPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "qa.db"
        self.enterContext(patch.object(storage, "DB_PATH", self.path))
        storage.initialize()

    def test_database_file_is_private(self):
        storage.save_slack_token(1, "secret-token")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_token_never_appears_in_slack_status(self):
        storage.save_slack_token(1, "secret-token")
        self.assertNotIn("secret-token", str(storage.get_slack_identity(1)))


if __name__ == "__main__":
    unittest.main()
