import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app import main, storage, slack_history
from app.current_user import get_current_user_id


class OwnershipAPITests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.enterContext(patch.object(storage,'DB_PATH',Path(temp.name)/'qa.db'))
        self.enterContext(patch('app.local_access.LOCAL_HOSTS', {'127.0.0.1','testclient'}))
        self.client=self.enterContext(TestClient(main.app,base_url='http://127.0.0.1'))
        self.user_id=1
        main.app.dependency_overrides[get_current_user_id]=lambda:self.user_id
        self.addCleanup(main.app.dependency_overrides.clear)
        with storage.connection() as db:
            db.execute("INSERT INTO users VALUES(2,'test','user-two','Second QA','now','now')")
        self.sender=self.enterContext(patch.object(main,'post_message',AsyncMock(side_effect=AssertionError('No network in ownership tests'))))
        self.task=self.create_task()
        self.path=f"/api/tasks/{self.task['id']}"
        self.settings={'fields':{'method':'User one method','password':'fixture-only'}}
        self.client.put(self.path+'/settings',json=self.settings)
        self.saved=self.client.post(self.path+'/sets',json={'name':'First set','settings':self.settings,'region':'TR','cases':[{'title':'A','text':'Steps'}]}).json()
        self.set_path=f"{self.path}/sets/{self.saved['id']}"
        self.case=self.saved['cases'][0]
        self.case_path=f"{self.set_path}/cases/{self.case['id']}"
        self.delivery=slack_history.record_send([self.case['id']],{'channel':'C_TEST','ts':'1.000002'})

    def create_task(self):
        response=self.client.post('/api/tasks',json={'jira_id':'QA-7','title':'Same Jira, independent task'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def test_same_jira_per_user_and_independent_settings(self):
        self.assertEqual(self.task['owner_user_id'],1)
        self.user_id=2
        self.assertEqual(self.client.get('/api/tasks?q=QA-7').json(),[])
        other=self.create_task()
        self.assertNotEqual(other['id'],self.task['id']);self.assertEqual(other['owner_user_id'],2)
        self.assertEqual(self.client.get(f"/api/tasks/{other['id']}/settings").json(),{})
        self.assertEqual(len(self.client.get('/api/tasks').json()),1)
        self.assertEqual(self.client.post('/api/tasks',json={'jira_id':'qa-7','title':'Duplicate'}).status_code,409)
        self.user_id=1
        self.assertEqual(self.client.get(self.path+'/settings').json()['fields'],self.settings['fields'])
        self.assertEqual(self.client.get('/api/tasks').json()[0]['id'],self.task['id'])

    def test_all_foreign_record_paths_return_404(self):
        self.user_id=2
        attempts=[('GET',self.path,None),('PUT',self.path,{'jira_id':'QA-9','title':'Wrong owner'}),
                  ('DELETE',self.path,None),('GET',self.path+'/settings',None),
                  ('PUT',self.path+'/settings',{'fields':{}}),('GET',self.path+'/sets',None),
                  ('POST',self.path+'/sets',{'name':'Other','region':'TR','settings':{},'cases':[{'title':'x','text':'y'}]}),
                  ('GET',self.set_path,None),('PATCH',self.case_path,{'status':'Failed'}),
                  ('POST',self.case_path+f'/slack-sends/{self.delivery}/permalink',None)]
        for method,path,payload in attempts:
            with self.subTest(method=method,path=path):
                self.assertEqual(self.client.request(method,path,json=payload).status_code,404)
        self.user_id=1
        self.assertEqual(self.client.get(self.set_path).json()['cases'][0]['status'],'Not tested')

    def test_request_cannot_choose_owner(self):
        self.client.app.dependency_overrides.clear()
        response=self.client.post('/api/tasks?user_id=2',headers={'X-User-ID':'2'},json={'jira_id':'QA-8','title':'Local identity'})
        self.assertEqual(response.json()['owner_user_id'],1)
        self.assertEqual(self.client.post('/api/tasks',json={'jira_id':'QA-9','title':'x','owner_user_id':2}).status_code,422)

    def test_slack_foreign_binding_blocked_before_post(self):
        self.user_id=2
        other=self.create_task()
        saved=self.client.post(f"/api/tasks/{other['id']}/sets",json={'name':'Other','region':'TR','settings':{},'cases':[{'title':'Other','text':'Other'}]}).json()
        self.user_id=1
        with patch.object(main,'USER_TOKEN','fake'),patch.object(main,'get_slack_route',return_value=('C_TEST',[])):
            response=self.client.post('/slack/send-cases',json={'region':'TR','mention_users':[],'cases':[{'title':'x','text':'y','case_ids':[saved['cases'][0]['id']]}]})
        self.assertEqual(response.status_code,404);self.sender.assert_not_awaited()
        with storage.connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO slack_send_cases VALUES(?,?)',(self.delivery,saved['cases'][0]['id']))
        self.user_id=2
        with patch.object(main,'USER_TOKEN','fake-local-token'):
            self.assertFalse(self.client.get('/api/slack-status').json()['connected'])
            self.assertEqual(self.client.post('/slack/send-cases',json={'region':'TR','cases':[{'title':'x','text':'y'}]}).status_code,403)
        self.sender.assert_not_awaited()

    def test_foreign_keys_and_no_implicit_owner_transfer(self):
        with storage.connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE tasks SET owner_user_id=2 WHERE id=?',(self.task['id'],))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE slack_sends SET owner_user_id=2 WHERE id=?',(self.delivery,))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM users WHERE id=1')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])


class OwnershipMigrationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'qa.db'
        self.enterContext(patch.object(storage,'DB_PATH',self.path))
        db=sqlite3.connect(self.path)
        db.executescript((Path(__file__).parent/'fixtures'/'pre_users.sql').read_text())
        db.execute("INSERT INTO tasks VALUES(42,'QA-7','Existing task','created','updated','{\"fields\":{\"method\":\"original\"}}')")
        db.execute("INSERT INTO case_sets VALUES(51,42,'Old run','created','{}','TR','deposit','[]')")
        db.execute("INSERT INTO test_cases VALUES(61,51,0,'Case','Body','Instructions','Request','Failed','QA note','[\"https://jira.example/browse/QA-9\"]','updated')")
        db.execute("INSERT INTO slack_sends VALUES(71,'C_OLD','123.000002','sent','https://example.slack.com/archives/C_OLD/p123000002',NULL,'checked')")
        db.execute('INSERT INTO slack_send_cases VALUES(71,61)')
        db.commit();db.close()

    def test_migration_preserves_ids_data_history_and_backup(self):
        with sqlite3.connect(self.path) as db:
            original={name:db.execute(f'SELECT * FROM {name}').fetchall() for name in ['tasks','case_sets','test_cases','slack_sends','slack_send_cases']}
        storage.initialize()
        with storage.connection() as db:
            self.assertEqual(dict(db.execute('SELECT * FROM tasks').fetchone())['owner_user_id'],1)
            self.assertEqual(db.execute('SELECT id FROM tasks').fetchone()[0],42)
            self.assertEqual(db.execute('SELECT owner_user_id FROM slack_sends').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT jira_id,title,created_at,updated_at,settings FROM tasks').fetchone()[:],original['tasks'][0][1:])
            for name in ('case_sets','test_cases','slack_send_cases'):
                self.assertEqual([tuple(r) for r in db.execute(f'SELECT * FROM {name}')],original[name])
            self.assertEqual(tuple(db.execute('SELECT id,channel,ts,sent_at,permalink,permalink_error,permalink_checked_at FROM slack_sends').fetchone()),original['slack_sends'][0])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        backups=list((self.path.parent/'backups').glob('*.db'));self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].stat().st_mode&0o777,0o600)
        with sqlite3.connect(backups[0]) as backup:
            for name in original:self.assertEqual(backup.execute(f'SELECT * FROM {name}').fetchall(),original[name])
            self.assertNotIn('owner_user_id',[r[1] for r in backup.execute('PRAGMA table_info(tasks)')])
        storage.initialize()
        self.assertEqual(len(list((self.path.parent/'backups').glob('*.db'))),1)

    def test_failed_integrity_check_rolls_back_upgrade(self):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO slack_send_cases VALUES(71,99999)')
        with self.assertRaisesRegex(RuntimeError,'rolled back'):storage.initialize()
        with sqlite3.connect(self.path) as db:
            self.assertNotIn('owner_user_id',[r[1] for r in db.execute('PRAGMA table_info(tasks)')])
            self.assertEqual(db.execute('SELECT id FROM tasks').fetchone()[0],42)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='users'").fetchone()[0],0)

    def test_newer_schema_is_not_downgraded(self):
        with sqlite3.connect(self.path) as db:db.execute('PRAGMA user_version=99')
        with self.assertRaisesRegex(RuntimeError,'newer'):storage.initialize()
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)


if __name__=='__main__':unittest.main()
