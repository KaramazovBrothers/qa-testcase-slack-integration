import unittest
import asyncio
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from app import main
from app.mentions import format_mentions, load_region_mentions

class MentionsTests(unittest.TestCase):
    def test_config_and_format(self):
        self.assertEqual(len(load_region_mentions()), 19)
        self.assertEqual(format_mentions(['@testuser1','U0123456789','@testuser1']), '@testuser1 <@U0123456789>')
        with self.assertRaises(ValueError):
            format_mentions(['<!channel>'])

    def test_send_overrides_and_empty_list(self):
        self.assertEqual(asyncio.run(main.region_mentions())['TR'], ['@testuser1','@testuser2'])
        cases=[{'title':'first','text':'body'}, {'title':'second','text':'edited body','comment':'extra'}]
        for operation in ['deposit','payout']:
            for users in [[], ['@testuser2'], ['U0123456789']]:
                sender=AsyncMock(return_value={'ts':'1.1'})
                with patch.object(main,'USER_TOKEN','test-only'), patch.object(main,'get_slack_route',return_value=('C_TEST',['U_MUST_NOT_RETURN'])), patch.object(main,'post_message',sender):
                    response=asyncio.run(main.slack_send_cases(main.SendCasesRequest(region='TR',cases=cases,operation=operation,mention_users=users)))
                self.assertEqual(response['sent'],2)
                calls=sender.call_args_list
                parents=[c.args[2] for c in calls if not c.kwargs.get('thread_ts')]
                self.assertEqual(len(parents),2)
                for parent in parents:
                    self.assertNotIn('U_MUST_NOT_RETURN',parent)
                    self.assertIn('выплаты' if operation=='payout' else 'депозита',parent)
                    self.assertTrue(parent.startswith(format_mentions(users)) if users else not parent.startswith("@"))
                self.assertEqual(len(calls),5)

    def test_individual_requests(self):
        sender = AsyncMock(return_value={'ts': '1.1'})
        cases = [{'title': 'Android Chrome', 'text': 'body', 'request_text': 'Custom first'}, {'title': 'Desktop Chrome', 'text': 'body', 'request_text': 'Custom second'}]
        with patch.object(main, 'USER_TOKEN', 'test-only'), patch.object(main, 'get_slack_route', return_value=('C_TEST', [])), patch.object(main, 'post_message', sender):
            asyncio.run(main.slack_send_cases(main.SendCasesRequest(region='TR', cases=cases, mention_users=['@testuser1'])))
        parents = [c.args[2] for c in sender.call_args_list if not c.kwargs.get('thread_ts')]
        self.assertEqual(parents, ['@testuser1 Custom first', '@testuser1 Custom second'])

    def test_invalid_mentions_do_not_send(self):
        sender=AsyncMock()
        with patch.object(main,'USER_TOKEN','test-only'), patch.object(main,'get_slack_route',return_value=('C_TEST',[])), patch.object(main,'post_message',sender):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(main.slack_send_cases(main.SendCasesRequest(region='TR',cases=[{'title':'test','text':'test'}],mention_users=['<!channel>'])))
        self.assertEqual(raised.exception.status_code,400)
        sender.assert_not_awaited()

if __name__=='__main__':
    unittest.main()
