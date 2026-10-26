"""Version 3: reusable test accounts scoped by owner and region."""
import sqlite3
from app.ownership_migration import backup_database


def migrate(path, backup_existing):
    db=sqlite3.connect(path,timeout=10)
    try:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA user_version').fetchone()[0]>=3:
            db.rollback();return
        if backup_existing:backup_database(path,'pre-region-accounts')
        for name in ('case_account_task_insert','case_account_task_update','accounts_task_immutable'):
            db.execute(f'DROP TRIGGER IF EXISTS {name}')
        db.execute('''CREATE TABLE region_accounts (
            id TEXT PRIMARY KEY, owner_user_id INTEGER NOT NULL REFERENCES users(id),
            region TEXT NOT NULL, name TEXT NOT NULL, account_id TEXT NOT NULL,
            login TEXT NOT NULL, password TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('main','usd'))
        )''')
        db.execute('''INSERT INTO region_accounts SELECT a.id,t.owner_user_id,coalesce(t.region,'TR'),
            a.name,a.account_id,a.login,a.password,a.kind FROM test_accounts a JOIN tasks t ON t.id=a.task_id''')
        db.execute('DROP TABLE test_accounts')
        db.execute('ALTER TABLE region_accounts RENAME TO test_accounts')
        db.execute('CREATE INDEX accounts_owner_region ON test_accounts(owner_user_id,region)')
        for op in ('INSERT','UPDATE'):
            db.execute(f'''CREATE TRIGGER case_account_region_{op.lower()} BEFORE {op} ON test_cases
                WHEN NEW.test_account_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM test_accounts a JOIN case_sets s ON s.id=NEW.set_id
                    JOIN tasks t ON t.id=s.task_id WHERE a.id=NEW.test_account_id
                    AND a.owner_user_id=t.owner_user_id AND a.region=s.region)
                BEGIN SELECT RAISE(ABORT,'Account belongs to a different owner or region'); END''')
        db.execute('''CREATE TRIGGER accounts_scope_immutable BEFORE UPDATE OF owner_user_id,region ON test_accounts
            WHEN NEW.owner_user_id IS NOT OLD.owner_user_id OR NEW.region IS NOT OLD.region
            BEGIN SELECT RAISE(ABORT,'Account scope cannot be changed'); END''')
        if db.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Region migration foreign key check failed')
        db.execute('PRAGMA user_version=3');db.commit()
    except BaseException:
        db.rollback();raise
    finally:db.close()
