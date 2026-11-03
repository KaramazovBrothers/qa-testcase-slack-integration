"""Every response that exposes user data must stay behind the local-access guard.

The tunnel is public, so a path missing from the protected list is reachable
from the internet. These tests pin the list to the routes that actually serve
workspace or token data, so adding a route without listing it fails here.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main, storage
from app.current_user import get_current_user_id

# Paths that must never be served to a request arriving through the tunnel.
PROTECTED = [
    ("GET", "/app"),
    ("GET", "/app/workspace.js"),
    ("GET", "/api/tasks"),
    ("GET", "/api/tasks/1"),
    ("GET", "/api/tasks/1/sets"),
    ("GET", "/api/tasks/1/sets/1"),
    ("GET", "/api/tasks/1/sets/1/cases/1/slack-replies"),
    ("GET", "/api/tasks/accounts?region=TR"),
    ("GET", "/generator"),
    ("POST", "/slack/send"),
    ("POST", "/slack/send-cases"),
    ("GET", "/api/slack-status"),
    ("GET", "/api/slack-diagnostics"),
]


class LocalAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        # Simulate a request that reached the app through the public tunnel.
        self.enterContext(patch("app.local_access.LOCAL_HOSTS", {"127.0.0.1", "testclient"}))
        self.client = self.enterContext(
            TestClient(main.app, base_url="http://public.ngrok.app", raise_server_exceptions=False)
        )
        main.app.dependency_overrides[get_current_user_id] = lambda: storage.LOCAL_USER_ID
        self.addCleanup(main.app.dependency_overrides.clear)

    def test_protected_paths_reject_public_requests(self):
        for method, path in PROTECTED:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json={})
                self.assertEqual(response.status_code, 403, f"{method} {path}")

    def test_forwarded_header_rejects_even_from_localhost(self):
        for method, path in PROTECTED:
            with self.subTest(method=method, path=path):
                response = self.client.request(
                    method, path, json={}, headers={"x-forwarded-for": "1.2.3.4"}
                )
                self.assertEqual(response.status_code, 403, f"{method} {path}")

    def test_cross_site_request_is_rejected(self):
        response = self.client.get("/api/tasks", headers={"sec-fetch-site": "cross-site"})
        self.assertEqual(response.status_code, 403)

    def test_oauth_callback_stays_public_for_slack(self):
        """Slack redirects the browser here, so the guard must not block it."""
        response = self.client.get("/slack/oauth/callback?code=x&state=y")
        self.assertNotEqual(response.status_code, 403)

    def test_events_endpoint_stays_public_for_slack(self):
        """Slack posts from its own servers; the signature is the guard."""
        response = self.client.post("/slack/events", json={})
        self.assertNotEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
