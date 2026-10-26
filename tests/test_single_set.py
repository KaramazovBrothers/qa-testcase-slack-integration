import unittest
import sqlite3
import test_unified_save
from app import storage


class SingleSetTests(unittest.TestCase):
    setUp=test_unified_save.UnifiedSaveTests.setUp
    draft=test_unified_save.UnifiedSaveTests.draft
    save=test_unified_save.UnifiedSaveTests.save
    with_cases=test_unified_save.UnifiedSaveTests.with_cases

    def test_upgrade_keeps_latest_set_and_backs_up_history(self):
        a=self.save(self.with_cases())
        with storage.connection() as db:
            db.execute('DROP INDEX one_set_per_task')
            latest=db.execute("INSERT INTO case_sets(task_id,name,created_at,settings,region,operation) VALUES(?,'Latest','now','{}','EC','payout')",(a['task']['id'],)).lastrowid
            db.execute("INSERT INTO test_cases(set_id,position,title,text,status,updated_at) VALUES(?,0,'Kept','Manual text','Failed','now')",(latest,))
            db.execute('PRAGMA user_version=3')
        storage.initialize()
        with storage.connection() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT id FROM case_sets')],[latest])
            self.assertEqual(tuple(db.execute('SELECT text,status FROM test_cases').fetchone()),('Manual text','Failed'))
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO case_sets(task_id,name,created_at,settings,region,operation) VALUES(?,'Duplicate','now','{}','EC','payout')",(a['task']['id'],))
        backups=list((storage.DB_PATH.parent/'backups').glob('*.pre-single-set.*.db'))
        self.assertEqual(len(backups),1)
        with sqlite3.connect(backups[0]) as backup:self.assertEqual(backup.execute('SELECT count(*) FROM case_sets').fetchone()[0],2)
        storage.initialize()
        self.assertEqual(len(list((storage.DB_PATH.parent/'backups').glob('*.pre-single-set.*.db'))),1)
