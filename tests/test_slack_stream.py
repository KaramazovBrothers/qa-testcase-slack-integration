"""The SSE bus that pushes a stored Slack reply to the open workspace tab."""
import asyncio
import json
import unittest

from app import slack_stream


class SlackStreamTests(unittest.TestCase):
    def tearDown(self):
        # A test must never leak a subscriber into the next one.
        for queue in list(slack_stream._subscribers):
            slack_stream.unsubscribe(queue)

    def test_publish_reaches_every_subscriber(self):
        first = slack_stream.subscribe()
        second = slack_stream.subscribe()
        slack_stream.publish({'type': 'reply', 'case_ids': [7]})
        self.assertEqual(first.get_nowait()['case_ids'], [7])
        self.assertEqual(second.get_nowait()['case_ids'], [7])

    def test_unsubscribe_stops_delivery(self):
        queue = slack_stream.subscribe()
        slack_stream.unsubscribe(queue)
        slack_stream.publish({'type': 'reply'})
        self.assertTrue(queue.empty())

    def test_full_queue_keeps_the_newest_event(self):
        queue = slack_stream.subscribe()
        for index in range(slack_stream._MAX_QUEUE):
            slack_stream.publish({'n': index})
        slack_stream.publish({'n': 'newest'})
        drained = []
        while not queue.empty():
            drained.append(queue.get_nowait()['n'])
        self.assertEqual(drained[-1], 'newest')
        self.assertEqual(len(drained), slack_stream._MAX_QUEUE)

    def test_publish_reply_shape(self):
        queue = slack_stream.subscribe()
        slack_stream.publish_reply(3, [1, 2], {'ts': '1.2', 'author_id': 'U1', 'text': 'hi', 'received_at': 'now'})
        event = queue.get_nowait()
        self.assertEqual(event['type'], 'reply')
        self.assertEqual(event['case_ids'], [1, 2])
        self.assertEqual(event['text'], 'hi')

    def test_stream_emits_retry_then_data_frame(self):
        async def scenario():
            queue = slack_stream.subscribe()
            frames = slack_stream.stream(queue)
            first = await frames.__anext__()
            slack_stream.publish({'type': 'reply', 'case_ids': [5]})
            second = await frames.__anext__()
            await frames.aclose()
            return first, second

        first, second = asyncio.run(scenario())
        self.assertTrue(first.startswith('retry:'))
        self.assertTrue(second.startswith('data: '))
        self.assertEqual(json.loads(second[len('data: '):])['case_ids'], [5])
        self.assertEqual(slack_stream.subscriber_count(), 0)

    def test_stream_sends_keep_alive_comments(self):
        async def scenario():
            queue = slack_stream.subscribe()
            frames = slack_stream.stream(queue, heartbeat=0.01)
            await frames.__anext__()  # retry
            frame = await frames.__anext__()
            await frames.aclose()
            return frame

        self.assertEqual(asyncio.run(scenario()), ': keep-alive\n\n')


if __name__ == '__main__':
    unittest.main()
