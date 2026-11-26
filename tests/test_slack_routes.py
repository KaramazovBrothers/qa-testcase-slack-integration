"""Slack routing is explicit: no default channel, no default people.

A QA request must never reach a guessed channel or ping a guessed person, so
`config/slack_routes.json` is the only source of truth and every gap is an
error instead of a silent fallback.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import slack_routes


class SlackRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "slack_routes.json"
        self.enterContext(patch.object(slack_routes, "ROUTES_PATH", self.path))

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_region_returns_its_own_channel_and_people(self):
        self.write({"TR": {"channel_id": "C_TR", "user_ids": ["U1", "U2"]}})
        channel, users = slack_routes.get_slack_route("TR")
        self.assertEqual(channel, "C_TR")
        self.assertEqual(users, ["U1", "U2"])

    def test_empty_people_list_is_allowed(self):
        """Sending without pinging anyone is a choice, not a misconfiguration."""
        self.write({"TR": {"channel_id": "C_TR", "user_ids": []}})
        channel, users = slack_routes.get_slack_route("TR")
        self.assertEqual(channel, "C_TR")
        self.assertEqual(users, [])

    def test_missing_file_refuses(self):
        with self.assertRaises(slack_routes.RouteNotConfigured):
            slack_routes.get_slack_route("TR")

    def test_unknown_region_refuses(self):
        self.write({"TR": {"channel_id": "C_TR", "user_ids": []}})
        with self.assertRaises(slack_routes.RouteNotConfigured) as caught:
            slack_routes.get_slack_route("GE")
        self.assertIn("GE", str(caught.exception))

    def test_no_default_entry_is_used(self):
        """A `default` key must not stand in for a missing region."""
        self.write({
            "TR": {"channel_id": "C_TR", "user_ids": []},
            "default": {"channel_id": "C_FALLBACK", "user_ids": []},
        })
        with self.assertRaises(slack_routes.RouteNotConfigured):
            slack_routes.get_slack_route("GE")

    def test_region_without_channel_refuses(self):
        self.write({"TR": {"user_ids": ["U1"]}})
        with self.assertRaises(slack_routes.RouteNotConfigured) as caught:
            slack_routes.get_slack_route("TR")
        self.assertIn("channel_id", str(caught.exception))

    def test_region_without_user_ids_key_refuses(self):
        """The list must be stated; silence is not treated as "nobody"."""
        self.write({"TR": {"channel_id": "C_TR"}})
        with self.assertRaises(slack_routes.RouteNotConfigured) as caught:
            slack_routes.get_slack_route("TR")
        self.assertIn("user_ids", str(caught.exception))

    def test_environment_cannot_supply_a_channel(self):
        self.write({"TR": {"channel_id": "C_TR", "user_ids": []}})
        with patch.dict("os.environ", {"SLACK_CHANNEL_ID": "C_FROM_ENV",
                                       "SLACK_MENTION_USER_IDS": "U_ENV"}):
            channel, users = slack_routes.get_slack_route("TR")
            self.assertEqual(channel, "C_TR")
            self.assertEqual(users, [])
            with self.assertRaises(slack_routes.RouteNotConfigured):
                slack_routes.get_slack_route("GE")


if __name__ == "__main__":
    unittest.main()
