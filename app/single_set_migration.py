"""Version 4: one editable case set per task; retain latest existing set."""
import sqlite3
from app.ownership_migration import backup_database


def migrate(path, backup_existing):
    db=sqlite3.connect(path,timeout=10)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA user_version').fetchone()[0]>=4:
            db.rollback();return
        if backup_existing:backup_database(path,'pre-single-set')
        db.execute('DELETE FROM case_sets WHERE id NOT IN (SELECT max(id) FROM case_sets GROUP BY task_id)')
        db.execute('CREATE UNIQUE INDEX one_set_per_task ON case_sets(task_id)')
        if db.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Single set migration integrity failure')
        db.execute('PRAGMA user_version=4');db.commit()
    except BaseException:
        db.rollback();raise
    finally:db.close()
