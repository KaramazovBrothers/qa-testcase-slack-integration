import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from app import main, storage
from app.slack_oauth import build_authorize_url


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'data' / 'qa_tests.db'
        self.db_patch = patch.object(storage, 'DB_PATH', self.path)
        self.db_patch.start()
        self.sender = AsyncMock(side_effect=AssertionError('Real Slack sending forbidden'))
        self.send_patch = patch.object(main, 'post_message', self.sender)
        self.send_patch.start()
        self.client = TestClient(main.app, base_url='http://127.0.0.1:8000')
        # Starlette 0.41 uses a fixed "testclient" peer. Simulate a local socket.
        self.peer_patch = patch('app.local_access.LOCAL_HOSTS', {'localhost','127.0.0.1','::1','testclient'})
        self.peer_patch.start()
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.peer_patch.stop()
        self.send_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def task(self, jira='QA-1'):
        response = self.client.post('/api/tasks', json={'jira_id':jira,'title':'Payment test'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()['id']

    def payload(self):
        return {'name':'Run 1','region':'TR','operation':'deposit','mention_users':[],
                'settings':{'fields':{'region':'TR','integration':'HPP','password':'local-test-only','qr':True}},
                'cases':[{'title':'Edited title','text':'Steps\nExpected','comment':'Extra instructions','request_text':'Please test'}]}

    def save(self, task):
        r=self.client.post(f'/api/tasks/{task}/sets',json=self.payload())
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def test_crud_search_validation(self):
        task=self.task('qa-123')
        self.assertEqual(self.client.get('/api/tasks?q=qa-123').json()[0]['jira_id'],'QA-123')
        self.assertEqual(self.client.post('/api/tasks',json={'jira_id':'QA-123','title':'x'}).status_code,409)
        self.assertEqual(self.client.post('/api/tasks',json={'jira_id':'bad','title':'x'}).status_code,422)
        self.assertEqual(self.client.put(f'/api/tasks/{task}',json={'jira_id':'PAY-3','title':'Updated'}).status_code,200)
        self.assertEqual(self.client.get(f'/api/tasks/{task}').json()['title'],'Updated')
        self.assertEqual(self.client.get('/api/tasks?q=missing').json(),[])
        self.assertEqual(self.client.get('/api/tasks/999999').status_code,404)
        self.assertEqual(self.client.delete(f'/api/tasks/{task}').status_code,204)
        self.assertEqual(self.client.delete(f'/api/tasks/{task}').status_code,404)

    def test_history_isolation_restart_and_cascade(self):
        a,b=self.task(),self.task('QA-2')
        first,second=self.save(a),self.save(a)
        other=self.save(b)
        case=first['cases'][0]
        path=f"/api/tasks/{a}/sets/{first['id']}/cases/{case['id']}"
        for status in ['Passed','Failed','Blocked','Skipped','Not tested']:
            self.assertEqual(self.client.patch(path,json={'status':status}).status_code,200)
        self.assertEqual(self.client.patch(path,json={'status':'Failed','qa_comment':'Issue found','bug_links':['https://jira.example/browse/QA-4']}).status_code,200)
        self.assertEqual(self.client.patch(path,json={'status':'Unknown'}).status_code,422)
        self.assertEqual(self.client.patch(path,json={'status':None}).status_code,422)
        self.assertEqual(self.client.patch(path,json={'bug_links':['javascript:alert(1)']}).status_code,422)
        self.assertEqual(self.client.get(f"/api/tasks/{b}/sets/{first['id']}").status_code,404)
        self.assertEqual(self.client.patch(f"/api/tasks/{b}/sets/{other['id']}/cases/{case['id']}",json={'status':'Passed'}).status_code,404)
        self.client.__exit__(None,None,None)
        self.client.__enter__()  # Lifespan + connection restart over the same file.
        loaded=self.client.get(f"/api/tasks/{a}/sets/{first['id']}").json()
        self.assertEqual(loaded['counts']['Failed'],1)
        self.assertEqual(loaded['cases'][0]['qa_comment'],'Issue found')
        self.assertEqual(loaded['cases'][0]['comment'],'Extra instructions')
        self.assertEqual(loaded['cases'][0]['bug_links'],['https://jira.example/browse/QA-4'])
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(self.client.get(f'/api/tasks/{a}/sets').json()),1)
        self.assertEqual(self.client.get(f'/api/tasks/{b}/sets/{other["id"]}').json()['counts']['Not tested'],1)
        self.client.delete(f'/api/tasks/{a}')
        with storage.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM case_sets').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM test_cases').fetchone()[0],1)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        self.sender.assert_not_awaited()

    def test_settings_and_invalid_set_are_atomic(self):
        a,b=self.task(),self.task('QA-2')
        settings={'fields':{'integration':'payout','license':'com','payoutAmount':'100','qr':True},'language':'uk','payout_fee_manual':True,'mention_edits':{'TR':['@testuser1']}}
        self.assertEqual(self.client.put(f'/api/tasks/{a}/settings',json=settings).status_code,200)
        self.assertEqual(self.client.get(f'/api/tasks/{a}/settings').json(),settings)
        self.assertEqual(self.client.get(f'/api/tasks/{b}/settings').json(),{})
        for fields in [{'region':'BAD'},{'qr':'yes'},{'amount':'-1'},{'unknown':'x'}]:
            self.assertEqual(self.client.put(f'/api/tasks/{a}/settings',json={'fields':fields}).status_code,422)
        invalid=self.payload();invalid['cases'].append({'title':'','text':'bad'})
        self.assertEqual(self.client.post(f'/api/tasks/{a}/sets',json=invalid).status_code,422)
        self.assertEqual(self.client.get(f'/api/tasks/{a}/sets').json(),[])
        self.assertEqual(self.client.get(f'/api/tasks/{a}/settings').json(),settings)

    def test_local_access_and_static(self):
        for path in ['/app','/app/workspace.js','/app/workspace.css','/generator','/api/tasks','/api/slack-status']:
            self.assertEqual(self.client.get(path).status_code,200,path)
            self.assertEqual(self.client.get(path,headers={'host':'example.ngrok.app'}).status_code,403,path)
            self.assertEqual(self.client.get(path,headers={'x-forwarded-host':'example.ngrok.app'}).status_code,403,path)
            self.assertEqual(self.client.get(path,headers={'origin':'https://evil.example'}).status_code,403,path)
            self.assertEqual(self.client.get(path,headers={'sec-fetch-site':'cross-site'}).status_code,403,path)
        self.assertEqual(self.client.get('/app/other').status_code,404)
        self.assertEqual(self.client.get('/slack/oauth/callback?code=x&state=invalid',headers={'host':'example.ngrok.app'}).status_code,400)
        with patch('app.local_access.LOCAL_HOSTS', {'127.0.0.1','localhost','::1'}):
            self.assertEqual(self.client.get('/app').status_code,403)
        self.assertEqual(self.client.get('/app').headers['cache-control'],'no-store')

    def test_saved_set_slack_and_user_oauth(self):
        task=self.task();saved=self.save(task)
        payload={key:saved[key] for key in ['region','operation','mention_users']}
        payload['cases']=[{key:saved['cases'][0][key] for key in ['title','text','comment','request_text']}]
        sender=AsyncMock(return_value={'ts':'123.1'})
        with patch.object(main,'USER_TOKEN','fake-user-token'),patch.object(main,'get_slack_route',return_value=('C_TEST',[])),patch.object(main,'post_message',sender):
            response=self.client.post('/slack/send-cases',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(sender.await_count,3)
        self.assertEqual(sender.call_args_list[0].args[2],'Please test')
        self.assertEqual(sender.call_args_list[1].args[2],'Edited title\n\nSteps\nExpected')
        self.assertEqual(sender.call_args_list[2].kwargs['thread_ts'],'123.1')
        with patch.dict('os.environ',{'SLACK_CLIENT_ID':'fake','SLACK_REDIRECT_URI':'https://example.test/slack/oauth/callback'}):
            url,state=build_authorize_url()
        query=parse_qs(urlsplit(url).query)
        self.assertEqual(query['user_scope'],['chat:write']);self.assertNotIn('scope',query)
        main.OAUTH_STATES.add('test-state')
        with patch.object(main,'USER_TOKEN',None),patch.object(main,'exchange_code',AsyncMock(return_value={'authed_user':{'access_token':'fake-user'}})):
            self.assertEqual(self.client.get('/slack/oauth/callback?state=test-state&code=fake').status_code,200)
            self.assertEqual(main.USER_TOKEN,'fake-user')
            self.assertEqual(self.client.get('/slack/oauth/callback?state=test-state&code=fake').status_code,400)


if __name__=='__main__':
    unittest.main()
