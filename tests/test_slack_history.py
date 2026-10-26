import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from app import main, storage, slack_history, slack_client


class SlackHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, 'DB_PATH', Path(self.temp.name) / 'qa.db'))
        self.enterContext(patch('app.local_access.LOCAL_HOSTS', {'127.0.0.1','testclient'}))
        self.enterContext(patch.object(main, 'USER_TOKEN', 'fake-user-token'))
        self.enterContext(patch.object(main, 'get_slack_route', return_value=('C_REQUESTED', [])))
        self.sender = self.enterContext(patch.object(main, 'post_message', AsyncMock()))
        self.lookup = self.enterContext(patch.object(slack_history, 'get_permalink', AsyncMock(return_value='https://example.slack.com/archives/C_ACTUAL/p1700000000000002')))
        self.client = self.enterContext(TestClient(main.app, base_url='http://127.0.0.1', raise_server_exceptions=False))
        self.task = self.client.post('/api/tasks', json={'jira_id':'QA-11','title':'Links'}).json()
        self.set_path = f"/api/tasks/{self.task['id']}/sets"
        self.saved = self.client.post(self.set_path, json={
            'name':'Run', 'settings':{}, 'region':'TR', 'mention_users':[],
            'cases':[{'title':'A','text':'Body A','comment':'More A','request_text':'Request A'},
                     {'title':'B','text':'Body B','request_text':'Request B'}]
        }).json()
        self.path = self.set_path + '/' + str(self.saved['id'])
        self.a, self.b = [c['id'] for c in self.saved['cases']]
        self.responses()

    def responses(self, suffix='2'):
        self.sender.side_effect = [
            {'channel':'C_ACTUAL','ts':'1700000000.000001'},
            {'channel':'C_ACTUAL','ts':'1700000000.00000'+suffix},
            {'channel':'C_ACTUAL','ts':'1700000000.000003'},
        ]

    def send(self, ids=None):
        return self.client.post('/slack/send-cases', json={
            'region':'TR','mention_users':[],
            'cases':[{'case_ids':ids if ids is not None else [self.a], 'title':'A', 'text':'Body A',
                      'comment':'More A', 'request_text':'Request A'}]})

    def history(self, index=0):
        return self.client.get(self.path).json()['cases'][index]['slack_sends']

    def retry(self, send_id, case_id=None, path=None):
        return self.client.post(f"{path or self.path}/cases/{case_id or self.a}/slack-sends/{send_id}/permalink")

    def test_response_metadata_exact_body_link_and_format(self):
        response = self.send()
        self.assertEqual(response.status_code,200,response.text)
        item = self.history()[0]
        self.assertEqual(item['channel'],'C_ACTUAL')  # Not the configured channel.
        self.assertEqual(item['ts'],'1700000000.000002')  # Body, not parent/comment.
        self.assertIsNotNone(item['sent_at'])
        self.assertEqual(item['permalink'],self.lookup.return_value)
        self.lookup.assert_awaited_once_with('fake-user-token','C_ACTUAL','1700000000.000002')
        calls=self.sender.call_args_list
        self.assertEqual(len(calls),3)
        self.assertEqual([call.args[2] for call in calls],['Request A','A\n\nBody A','Дополнительная информация:\nMore A'])
        self.assertEqual(calls[1].kwargs,{'thread_ts':'1700000000.000001'})
        self.assertEqual(calls[2].kwargs,{'thread_ts':'1700000000.000001'})
        self.assertEqual(self.history(1),[])

    def test_lookup_failure_commits_first_and_retry_never_posts(self):
        async def fail(*args):
            pending=self.history()[0]
            self.assertEqual(pending['ts'],'1700000000.000002')
            self.assertIsNone(pending['permalink'])
            raise httpx.ReadTimeout('secret must not be stored')
        self.lookup.side_effect=fail
        response=self.send()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['sent'],1)
        failed=self.history()[0]
        self.assertIsNone(failed['permalink'])
        self.assertNotIn('secret',failed['permalink_error'])
        self.assertEqual(self.sender.await_count,3)
        self.sender.reset_mock()
        self.lookup.side_effect=RuntimeError('still unavailable')
        retry=self.retry(failed['id'])
        self.assertEqual(retry.status_code,200)
        self.assertIsNone(retry.json()['permalink'])
        self.lookup.side_effect=None
        retry=self.retry(failed['id'])
        self.assertEqual(retry.status_code,200)
        self.assertEqual(retry.json()['permalink'],self.lookup.return_value)
        self.assertEqual(retry.json()['sent_at'],failed['sent_at'])
        self.assertEqual(len(self.history()),1)
        self.lookup.reset_mock()
        self.assertEqual(self.retry(failed['id']).status_code,200)
        self.lookup.assert_not_awaited()  # Existing links are returned without HTTP.
        self.sender.assert_not_awaited()

    def test_multiple_sends_and_restart(self):
        self.assertEqual(self.send().status_code,200)
        self.responses('4')
        self.assertEqual(self.send().status_code,200)
        with TestClient(main.app,base_url='http://127.0.0.1') as restarted:
            history=restarted.get(self.path).json()['cases'][0]['slack_sends']
        self.assertEqual([h['ts'] for h in history],['1700000000.000004','1700000000.000002'])
        self.assertNotEqual(history[0]['id'],history[1]['id'])

    def test_shared_message_has_one_delivery_and_one_lookup(self):
        self.assertEqual(self.send([self.a,self.b,self.a]).status_code,200)
        self.assertEqual(self.history(),self.history(1))
        self.lookup.assert_awaited_once()
        with storage.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM slack_sends').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM slack_send_cases').fetchone()[0],2)
        self.client.delete(f"/api/tasks/{self.task['id']}")
        with storage.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM slack_sends').fetchone()[0],0)

    def test_partial_send_failure_preserves_acknowledged_body(self):
        self.sender.side_effect=[{'channel':'C_ACTUAL','ts':'1.1'}, {'channel':'C_ACTUAL','ts':'1.2'}, RuntimeError('comment failed')]
        response=self.send()
        self.assertEqual(response.status_code,500)
        self.assertEqual(self.history()[0]['ts'],'1.2')
        self.assertEqual(self.sender.await_count,3)

    def test_invalid_binding_rejected_before_posting(self):
        self.assertEqual(self.send([self.a,999999]).status_code,404)
        self.assertEqual(self.send([-1]).status_code,422)
        self.assertEqual(self.send(['1']).status_code,422)
        self.sender.assert_not_awaited();self.lookup.assert_not_awaited()

    def test_retry_checks_ownership_token_and_local_access(self):
        self.lookup.side_effect=RuntimeError('lookup failed')
        self.send();item=self.history()[0];self.sender.reset_mock();self.lookup.reset_mock()
        self.assertEqual(self.retry(item['id'],case_id=self.b).status_code,404)
        self.assertEqual(self.retry(item['id'],path='/api/tasks/999/sets/'+str(self.saved['id'])).status_code,404)
        with patch.object(main,'USER_TOKEN',None):
            self.assertEqual(self.retry(item['id']).status_code,401)
        self.lookup.assert_not_awaited();self.sender.assert_not_awaited()
        path=f"{self.path}/cases/{self.a}/slack-sends/{item['id']}/permalink"
        self.assertEqual(self.client.post(path,headers={'host':'public.ngrok.app'}).status_code,403)

    def test_existing_database_upgrade_is_additive(self):
        with storage.connection() as db:
            db.executescript('DROP TABLE slack_send_cases; DROP TABLE slack_sends;')
        storage.initialize();storage.initialize()
        self.assertEqual(self.client.get(self.path).json()['cases'][0]['text'],'Body A')
        self.assertEqual(self.send().status_code,200)
        self.assertEqual(len(self.history()),1)


class SlackPermalinkClientTests(unittest.TestCase):
    def call_with_response(self, payload, status=200):
        real_client=httpx.AsyncClient
        requests=[]
        def handle(request):
            requests.append(request)
            return httpx.Response(status,json=payload)
        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(handle),**kwargs)
        with patch.object(slack_client.httpx,'AsyncClient',side_effect=client):
            result=asyncio.run(slack_client.get_permalink('test-user-token','C_EXACT','1700000000.000002'))
        return result,requests

    def test_get_contract_and_auth_header(self):
        link='https://example.slack.com/archives/C_EXACT/p1700000000000002?thread_ts=1700000000.000001'
        result,requests=self.call_with_response({'ok':True,'permalink':link})
        self.assertEqual(result,link)
        request=requests[0]
        self.assertEqual(request.method,'GET')
        self.assertEqual(request.url.path,'/api/chat.getPermalink')
        self.assertEqual(dict(request.url.params),{'channel':'C_EXACT','message_ts':'1700000000.000002'})
        self.assertEqual(request.headers['authorization'],'Bearer test-user-token')

    def test_slack_error_rate_limit_and_invalid_link(self):
        for payload,status,error in [({'ok':False,'error':'missing_scope'},200,RuntimeError),
                                     ({'ok':False},429,httpx.HTTPStatusError),
                                     ({'ok':True,'permalink':'javascript:alert(1)'},200,ValueError),
                                     ({'ok':True},200,ValueError)]:
            with self.subTest(payload=payload,status=status),self.assertRaises(error):
                self.call_with_response(payload,status)


if __name__=='__main__':
    unittest.main()
