import unittest
import test_unified_save
from app import storage,main
from app.current_user import get_current_user_id


class RegionAccountsTests(unittest.TestCase):
    setUp=test_unified_save.UnifiedSaveTests.setUp
    draft=test_unified_save.UnifiedSaveTests.draft
    save=test_unified_save.UnifiedSaveTests.save
    with_cases=test_unified_save.UnifiedSaveTests.with_cases
    def test_reuse_between_tasks_region_filter_and_explicit_delete(self):
        p=self.with_cases();first=self.save(p)
        p=self.with_cases();p['client_key']='second';second=self.save(p)
        self.assertEqual(first['set']['cases'][0]['test_account_id'],second['set']['cases'][0]['test_account_id'])
        self.assertEqual(len(self.client.get('/api/tasks/accounts?region=EC').json()),1)
        self.assertEqual(self.client.get('/api/tasks/accounts?region=TR').json(),[])
        # An empty list must not delete other tasks' regional accounts.
        self.save(self.draft('third'))
        self.assertEqual(len(self.client.get('/api/tasks/accounts?region=EC').json()),1)
        self.client.delete(f"/api/tasks/{first['task']['id']}")
        self.assertEqual(len(self.client.get('/api/tasks/accounts?region=EC').json()),1)
        response=self.client.post('/api/tasks/accounts',json={'region':'EC','deleted_account_ids':['account1']})
        self.assertEqual(response.status_code,200,response.text)
        restored=self.client.get(f"/api/tasks/{second['task']['id']}/sets/{second['set']['id']}").json()
        self.assertIsNone(restored['cases'][0]['test_account_id']);self.assertIn('AccountID: 123',restored['cases'][0]['text'])

    def test_deduplication_remaps_new_case_assignment(self):
        a=self.save(self.with_cases());p=self.with_cases();p['client_key']='duplicate-entry';p['test_accounts'][0]['id']='different-id';p['cases'][0]['test_account_id']='different-id'
        b=self.save(p)
        self.assertEqual(b['set']['cases'][0]['test_account_id'],'account1')
        self.assertEqual(len(b['task']['test_accounts']),1)
        storage.initialize()
        self.assertEqual(len(self.client.get('/api/tasks/accounts?region=EC').json()),1)

    def test_owner_and_region_access_isolation(self):
        a=self.save(self.with_cases())
        with storage.connection() as db:
            db.execute("INSERT INTO users VALUES(2,'test','other','Other','now','now')")
        main.app.dependency_overrides[get_current_user_id]=lambda:2
        self.addCleanup(main.app.dependency_overrides.clear)
        self.assertEqual(self.client.get('/api/tasks/accounts?region=EC').json(),[])
        response=self.client.post('/api/tasks/accounts',json={'region':'EC','test_accounts':self.with_cases()['test_accounts']})
        self.assertEqual(response.status_code,404)
        response=self.client.post('/api/tasks/accounts',json={'region':'EC','deleted_account_ids':['account1']})
        self.assertEqual(response.status_code,404)
        main.app.dependency_overrides.clear()
        response=self.client.post('/api/tasks/accounts',json={'region':'TR','test_accounts':self.with_cases()['test_accounts']})
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.client.get('/api/tasks/accounts?region=invalid').status_code,422)

    def test_standalone_account_save_no_task(self):
        response=self.client.post('/api/tasks/accounts',json={'region':'EC','test_accounts':self.with_cases()['test_accounts']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/tasks').json(),[])
        response=self.client.post('/api/tasks/accounts',json={'region':'EC','test_accounts':self.with_cases()['test_accounts']})
        self.assertEqual(len(response.json()['accounts']),1)
        self.sender.assert_not_awaited()
