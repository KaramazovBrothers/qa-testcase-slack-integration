import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app import main, storage


class UnifiedSaveTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.enterContext(patch.object(storage,'DB_PATH',Path(temp.name)/'qa.db'))
        self.enterContext(patch('app.local_access.LOCAL_HOSTS',{'127.0.0.1','testclient'}))
        self.sender=self.enterContext(patch.object(main,'post_message',AsyncMock(side_effect=AssertionError('No real Slack'))))
        self.client=self.enterContext(TestClient(main.app,base_url='http://127.0.0.1'))

    def draft(self,key='draft'):
        return {'client_key':key,'settings':{'fields':{'region':'EC','integration':'payout'},'mention_edits':{'TR':['@old'],'EC':['@current']}},'test_accounts':[]}

    def save(self,p):
        r=self.client.post('/api/tasks/save',json=p)
        self.assertIn(r.status_code,(200,201),r.text)
        return r.json()

    def with_cases(self):
        p=self.draft();p.update(generation_key='gen1',cases=[{'client_key':'case1','title':'Case','text':'AccountID: old\nlogin: old\nPassword: old\n\nKeep these steps','test_account_id':'account1'}],test_accounts=[{'id':'account1','name':'Tester','account_id':'123','login':'test@example.invalid','password':'local-only'}]);return p

    def test_unnamed_idempotency_and_single_region(self):
        p=self.draft();a=self.save(p);b=self.save(p)
        self.assertEqual(a['task']['id'],b['task']['id']);self.assertEqual(a['task']['title'],'Без названия 1')
        self.assertIsNone(a['task']['jira_id']);self.assertEqual(a['task']['settings']['mention_edits'],{'EC':['@current']})
        p=self.draft('second');p['jira_id']='QA-7';self.assertEqual(self.save(p)['task']['title'],'Без названия 2')
        p['settings']['fields']['region']='TR';self.assertEqual(self.client.post('/api/tasks/save',json=p).status_code,409)
        self.assertEqual(len(self.client.get('/api/tasks').json()),2)

    def test_assign_edit_replace_and_delete_single_set(self):
        p=self.with_cases();a=self.save(p);case=a['set']['cases'][0]
        self.assertIn('AccountID: 123',case['text']);self.assertIn('Keep these steps',case['text'])
        self.assertEqual(case['test_account_id'],'account1')
        p['task_id']=a['task']['id'];p['set_id']=a['set']['id'];p['cases'][0]['id']=case['id'];p['cases'][0]['text']=case['text']+'\nManual edit';p['cases'][0]['status']='Passed'
        b=self.save(p);self.assertEqual(b['set']['cases'][0]['id'],case['id']);self.assertIn('Manual edit',b['set']['cases'][0]['text'])
        p.pop('set_id');p['generation_key']='gen2';p['cases'][0].pop('id');p['cases'][0]['client_key']='case2';c=self.save(p)
        self.assertEqual(c['set']['id'],a['set']['id']);self.assertEqual(len(self.client.get(f"/api/tasks/{a['task']['id']}/sets").json()),1)
        p['set_id']=c['set']['id'];p['test_accounts']=[];p['deleted_account_ids']=['account1'];p['cases'][0]['test_account_id']=None;self.save(p)
        saved=self.client.get(f"/api/tasks/{a['task']['id']}/sets/{a['set']['id']}").json()
        self.assertIsNone(saved['cases'][0]['test_account_id']);self.assertIn('AccountID: 123',saved['cases'][0]['text'])
        p['cases']=[];self.assertEqual(self.save(p)['set']['cases'],[])
        storage.initialize();self.assertEqual(len(self.client.get('/api/tasks').json()),1)
        self.sender.assert_not_awaited()

    def test_cross_task_account_rejected_and_transaction_rolled_back(self):
        a=self.save(self.with_cases());p=self.with_cases();p['client_key']='another';p['settings']['fields']['region']='TR'
        self.assertEqual(self.client.post('/api/tasks/save',json=p).status_code,404)
        self.assertEqual(len(self.client.get('/api/tasks').json()),1)
        p=self.with_cases();p['task_id']=a['task']['id'];p['cases'][0]['id']=99999
        self.assertEqual(self.client.post('/api/tasks/save',json=p).status_code,404)
        self.assertEqual(len(self.client.get(f"/api/tasks/{a['task']['id']}/sets").json()),1)

    def test_legacy_region_guard_and_case_delete(self):
        a=self.save(self.with_cases());tid=a['task']['id'];sid=a['set']['id'];cid=a['set']['cases'][0]['id']
        self.assertEqual(self.client.put(f'/api/tasks/{tid}/settings',json={'fields':{'region':'TR'}}).status_code,409)
        self.assertEqual(self.client.delete(f'/api/tasks/{tid}/sets/{sid}/cases/{cid}').status_code,204)
        self.assertEqual(self.client.get(f'/api/tasks/{tid}/sets/{sid}').json()['cases'],[])
