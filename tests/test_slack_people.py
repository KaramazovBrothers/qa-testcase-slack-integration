"""Pasting a Slack profile link must be enough to mention a person by name.

People copy a link out of Slack, not a member ID. Accepting the link, then
showing the display name while storing the ID, keeps the UI obvious without
weakening the API call (Slack only notifies on `<@U…>`).
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import main, slack_people, storage
from app.current_user import get_current_user_id
from app.mentions import extract_member_id, normalize_mentions

PROFILE_LINK = "https://hglobal.enterprise.slack.com/team/U04BNNL48KF"


class LinkParsingTests(unittest.TestCase):
    def test_profile_link_yields_the_member_id(self):
        self.assertEqual(extract_member_id(PROFILE_LINK), "U04BNNL48KF")

    def test_link_with_trailing_slash_and_query(self):
        self.assertEqual(extract_member_id(PROFILE_LINK + "/"), "U04BNNL48KF")
        self.assertEqual(extract_member_id(PROFILE_LINK + "?foo=1"), "U04BNNL48KF")

    def test_other_link_forms(self):
        self.assertEqual(extract_member_id("https://redcore.slack.com/team/U99/"), "U99")
        self.assertEqual(extract_member_id("<@U04BNNL48KF>"), "U04BNNL48KF")
        self.assertEqual(extract_member_id("<@U04BNNL48KF|ilyos>"), "U04BNNL48KF")
        self.assertEqual(extract_member_id("U04BNNL48KF"), "U04BNNL48KF")
        self.assertEqual(extract_member_id("@U04BNNL48KF"), "U04BNNL48KF")

    def test_enterprise_user_prefix_is_accepted(self):
        self.assertEqual(extract_member_id("W04BNNL48KF"), "W04BNNL48KF")

    def test_usernames_are_not_mistaken_for_ids(self):
        self.assertIsNone(extract_member_id("@ilyos.ismoilov"))
        self.assertIsNone(extract_member_id("ilyos"))
        self.assertIsNone(extract_member_id("@Ilyos Ismoilov"))

    def test_normalize_keeps_the_id_and_drops_duplicates(self):
        self.assertEqual(
            normalize_mentions([PROFILE_LINK, "U04BNNL48KF", "<@U04BNNL48KF>"]),
            ["U04BNNL48KF"],
        )

    def test_normalize_accepts_a_mixed_list(self):
        self.assertEqual(
            normalize_mentions([PROFILE_LINK, "@ilyos.ismoilov"]),
            ["U04BNNL48KF", "ilyos.ismoilov"],
        )

    def test_unrelated_url_is_rejected_with_guidance(self):
        with self.assertRaises(ValueError) as caught:
            normalize_mentions(["https://example.com/not-a-profile"])
        self.assertIn("profile link", str(caught.exception))


class PeopleCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        storage.initialize()

    def test_remember_then_read_from_cache(self):
        slack_people.remember("U1", "Ilyos Ismoilov", team_id="T1")
        self.assertEqual(slack_people.cached("U1"), "Ilyos Ismoilov")
        self.assertFalse(slack_people.is_stale("U1"))

    def test_unknown_person_has_no_name(self):
        self.assertIsNone(slack_people.cached("U404"))
        self.assertTrue(slack_people.is_stale("U404"))

    def test_remember_updates_an_existing_row(self):
        slack_people.remember("U1", "Old Name")
        slack_people.remember("U1", "New Name")
        self.assertEqual(slack_people.cached("U1"), "New Name")
        self.assertEqual(slack_people.all_cached(), {"U1": "New Name"})

    def test_stale_entry_is_refreshed(self):
        slack_people.remember("U1", "Old Name")
        with storage.connection() as db:
            db.execute(
                "UPDATE slack_people SET fetched_at='2000-01-01T00:00:00+00:00' WHERE slack_user_id=?",
                ("U1",),
            )
        self.assertTrue(slack_people.is_stale("U1"))


class DisplayNameTests(unittest.TestCase):
    def test_prefers_display_name_then_real_name(self):
        user = {
            "name": "ilyos",
            "real_name": "Ilyos Ismoilov",
            "profile": {"display_name": "Ilyos", "real_name": "Ilyos Ismoilov"},
        }
        self.assertEqual(slack_people.display_name(user), "Ilyos")

    def test_falls_back_to_real_name_without_display_name(self):
        user = {"name": "ilyos", "real_name": "Ilyos Ismoilov", "profile": {}}
        self.assertEqual(slack_people.display_name(user), "Ilyos Ismoilov")

    def test_falls_back_to_login_when_nothing_else_is_set(self):
        user = {"name": "ilyos", "profile": {}}
        self.assertEqual(slack_people.display_name(user), "ilyos")

    def test_empty_user_yields_empty_string(self):
        self.assertEqual(slack_people.display_name({}), "")


class ResolveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        storage.initialize()

    async def test_slack_result_is_returned_and_cached(self):
        user = {"name": "ilyos", "profile": {"display_name": "Ilyos"}}
        with patch.object(slack_people, "fetch_user", AsyncMock(return_value=user)):
            name = await slack_people.resolve("token", "U1")
        self.assertEqual(name, "Ilyos")
        self.assertEqual(slack_people.cached("U1"), "Ilyos")

    async def test_failure_keeps_the_id_and_returns_no_name(self):
        with patch.object(slack_people, "fetch_user", AsyncMock(return_value=None)):
            name = await slack_people.resolve("token", "U1")
        self.assertIsNone(name)
        self.assertIsNone(slack_people.cached("U1"))

    async def test_missing_token_does_not_call_slack(self):
        fetcher = AsyncMock()
        with patch.object(slack_people, "fetch_user", fetcher):
            self.assertIsNone(await slack_people.resolve(None, "U1"))
        fetcher.assert_not_awaited()

    async def test_cached_name_is_used_without_a_call(self):
        slack_people.remember("U1", "Cached Person")
        fetcher = AsyncMock()
        with patch.object(slack_people, "fetch_user", fetcher):
            self.assertEqual(await slack_people.resolve("token", "U1"), "Cached Person")
        fetcher.assert_not_awaited()

    async def test_refresh_forces_a_call(self):
        slack_people.remember("U1", "Old Name")
        user = {"name": "ilyos", "profile": {"display_name": "New Name"}}
        fetcher = AsyncMock(return_value=user)
        with patch.object(slack_people, "fetch_user", fetcher):
            self.assertEqual(await slack_people.resolve("token", "U1", refresh=True), "New Name")
        fetcher.assert_awaited_once()

    async def test_fetch_user_survives_a_slack_error(self):
        response = httpx.Response(200, json={"ok": False, "error": "missing_scope"})
        with patch.object(httpx.AsyncClient, "get", AsyncMock(return_value=response)):
            self.assertIsNone(await slack_people.fetch_user("token", "U1"))

    async def test_fetch_user_survives_a_network_error(self):
        with patch.object(httpx.AsyncClient, "get", AsyncMock(side_effect=httpx.ConnectError("down"))):
            self.assertIsNone(await slack_people.fetch_user("token", "U1"))


class PeopleEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        self.enterContext(patch("app.local_access.LOCAL_HOSTS", {"127.0.0.1", "testclient"}))
        storage.initialize()
        self.client = self.enterContext(
            TestClient(main.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        )
        main.app.dependency_overrides[get_current_user_id] = lambda: storage.LOCAL_USER_ID
        self.addCleanup(main.app.dependency_overrides.clear)

    def test_link_is_resolved_to_id_and_name(self):
        user = {"name": "ilyos", "profile": {"display_name": "Ilyos Ismoilov"}}
        with patch.object(storage, "get_slack_token", return_value="token"), \
                patch.object(slack_people, "fetch_user", AsyncMock(return_value=user)):
            response = self.client.post("/api/slack/people", json={"entries": [PROFILE_LINK]})
        self.assertEqual(response.status_code, 200, response.text)
        people = response.json()["people"]
        self.assertEqual(people[0]["id"], "U04BNNL48KF")
        self.assertEqual(people[0]["name"], "Ilyos Ismoilov")
        self.assertEqual(people[0]["label"], "Ilyos Ismoilov")

    def test_no_token_still_returns_the_id(self):
        with patch.object(storage, "get_slack_token", return_value=None):
            response = self.client.post("/api/slack/people", json={"entries": [PROFILE_LINK]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["people"][0]["label"], "U04BNNL48KF")

    def test_invalid_entry_is_a_400_with_guidance(self):
        with patch.object(storage, "get_slack_token", return_value=None):
            response = self.client.post("/api/slack/people", json={"entries": ["@Ilyos Ismoilov"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("profile link", response.json()["detail"])

    def test_endpoint_is_not_reachable_through_the_tunnel(self):
        public = self.enterContext(
            TestClient(main.app, base_url="http://public.ngrok.app", raise_server_exceptions=False)
        )
        self.assertEqual(public.post("/api/slack/people", json={"entries": []}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
