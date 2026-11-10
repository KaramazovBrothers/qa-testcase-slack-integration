"""Reply replay across workers.

Behind a reverse proxy the Events API call and the browser's SSE connection can
land on different processes. Each published event is therefore filed, and a
stream replays the file on connect, so a reply is never lost to the process
boundary.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import slack_stream, storage


class ReplyReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, "DB_PATH", Path(self.temp.name) / "qa.db"))
        storage.initialize()

    def test_published_reply_is_replayable_for_another_worker(self):
        # No subscriber in this process: exactly what the Events API worker sees
        # when the tab is connected elsewhere.
        slack_stream.publish_reply(7, [11, 12], {
            "ts": "1700000000.000100",
            "author_id": "U123",
            "text": "ready",
            "received_at": "2026-11-10T10:00:00+00:00",
        }, event_id="Ev100")

        events = slack_stream.replay(None)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "reply")
        self.assertEqual(events[0]["case_ids"], [11, 12])
        self.assertEqual(events[0]["ts"], "1700000000.000100")
        self.assertEqual(events[0]["author"], "U123")

    def test_event_is_filed_once(self):
        reply = {"ts": "1700000000.000200", "text": "hello"}
        slack_stream.publish_reply(7, [11], reply, event_id="Ev200")
        slack_stream.publish_reply(7, [11], reply, event_id="Ev200")
        self.assertEqual(len(slack_stream.replay(None)), 1)

    def test_prune_drops_old_events(self):
        slack_stream.publish_reply(7, [11], {"ts": "1", "text": "old"}, event_id="Ev300")
        self.assertEqual(slack_stream.prune("2999-01-01T00:00:00+00:00"), 1)
        self.assertEqual(slack_stream.replay(None), [])


if __name__ == "__main__":
    unittest.main()
