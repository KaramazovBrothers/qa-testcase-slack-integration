"""Identity behind a trusted reverse proxy (QAHELPER_ACCESS_MODE=proxy).

Two things matter for a production deployment:
  * the workspace is served to a proxied host once proxy mode is on, while a
    foreign Origin is still refused;
  * the person is identified by the proxy header, and each identity gets its own
    `users` row, so one tester never sees another's tasks.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main, storage
from app.current_user import get_current_user_id

PROXY_ENV = {"QAHELPER_ACCESS_MODE": "proxy"}
HEADER = "x-auth-request-email"


class ProxyModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        storage.initialize()
        # The proxy terminates TLS and forwards headers; the app sees a
        # non-loopback host and peer in that case.
        self.enterContext(patch.dict("os.environ", PROXY_ENV))
        self.client = self.enterContext(
            TestClient(main.app, base_url="https://qahelper.corp.example", raise_server_exceptions=False)
        )
        main.app.dependency_overrides.clear()
        self.addCleanup(main.app.dependency_overrides.clear)

    def test_workspace_is_served_through_the_proxy(self):
        response = self.client.get("/app", headers={HEADER: "alice@corp.example"})
        self.assertEqual(response.status_code, 200)

    def test_forwarded_headers_are_expected_and_accepted(self):
        response = self.client.get(
            "/api/tasks",
            headers={HEADER: "alice@corp.example",
                     "x-forwarded-for": "10.0.0.5",
                     "x-forwarded-proto": "https"},
        )
        self.assertEqual(response.status_code, 200)

    def test_foreign_origin_is_still_refused(self):
        response = self.client.get(
            "/api/tasks",
            headers={HEADER: "alice@corp.example", "origin": "https://evil.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_identity_is_unauthorised(self):
        response = self.client.get("/api/tasks")
        self.assertEqual(response.status_code, 401)

    def test_each_identity_gets_its_own_tasks(self):
        alice = self.client.post("/api/tasks", json={"title": "alice task"},
                                 headers={HEADER: "alice@corp.example"})
        self.assertEqual(alice.status_code, 201)
        bob = self.client.post("/api/tasks", json={"title": "bob task"},
                               headers={HEADER: "bob@corp.example"})
        self.assertEqual(bob.status_code, 201)

        alice_list = self.client.get("/api/tasks", headers={HEADER: "alice@corp.example"}).json()
        bob_list = self.client.get("/api/tasks", headers={HEADER: "bob@corp.example"}).json()
        self.assertEqual([t["title"] for t in alice_list], ["alice task"])
        self.assertEqual([t["title"] for t in bob_list], ["bob task"])

    def test_same_identity_reuses_one_row(self):
        self.client.get("/api/tasks", headers={HEADER: "alice@corp.example"})
        self.client.get("/api/tasks", headers={HEADER: "alice@corp.example"})
        self.assertEqual(storage.ensure_user("sso", "alice@corp.example"),
                         storage.ensure_user("sso", "alice@corp.example"))
        with storage.connection() as db:
            count = db.execute(
                "SELECT count(*) FROM users WHERE auth_subject=?", ("alice@corp.example",)
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_identity_header_is_configurable(self):
        with patch.dict("os.environ", {"QAHELPER_IDENTITY_HEADER": "X-Forwarded-User"}):
            ok = self.client.get("/api/tasks", headers={"x-forwarded-user": "carol@corp.example"})
            missing = self.client.get("/api/tasks", headers={HEADER: "carol@corp.example"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(missing.status_code, 401)


class LocalModeTests(unittest.TestCase):
    """The proxy header must mean nothing while the app runs on loopback."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        storage.initialize()
        self.enterContext(patch("app.local_access.LOCAL_HOSTS", {'127.0.0.1', 'testclient'}))
        self.client = self.enterContext(
            TestClient(main.app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
        )
        main.app.dependency_overrides[get_current_user_id] = lambda: storage.LOCAL_USER_ID
        self.addCleanup(main.app.dependency_overrides.clear)

    def test_header_cannot_switch_identity_locally(self):
        created = self.client.post("/api/tasks", json={"title": "local"},
                                   headers={HEADER: "alice@corp.example"})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["owner_user_id"], storage.LOCAL_USER_ID)


if __name__ == "__main__":
    unittest.main()
