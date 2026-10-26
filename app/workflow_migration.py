"""Version 2: optional Jira, atomic-save keys and task-local test accounts."""
import json
import sqlite3
from app.ownership_migration import backup_database


def single_region(settings, region):
    result = dict(settings)
    edits = result.get('mention_edits', {})
    if 'mention_edits' in result:
        result['mention_edits'] = {region: edits[region]} if region in edits else {}
    return result


def migrate(db_path, backup_existing):
    db = sqlite3.connect(db_path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA user_version').fetchone()[0] >= 2:
            db.rollback()
            return
        if backup_existing:
            backup_database(db_path, 'pre-workflow')
        for name in ('tasks_owner_immutable','slack_link_owner_insert','slack_link_owner_update'):
            db.execute(f'DROP TRIGGER IF EXISTS {name}')
        db.execute('''CREATE TABLE tasks_v2 (
            id INTEGER PRIMARY KEY,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            jira_id TEXT COLLATE NOCASE, title TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            settings TEXT NOT NULL DEFAULT '{}', region TEXT, client_key TEXT,
            UNIQUE(owner_user_id,jira_id), UNIQUE(owner_user_id,client_key)
        )''')
        for row in db.execute('SELECT * FROM tasks').fetchall():
            settings = json.loads(row['settings'])
            latest = db.execute('SELECT region FROM case_sets WHERE task_id=? ORDER BY id DESC LIMIT 1', (row['id'],)).fetchone()
            region = settings.get('fields',{}).get('region') or (latest['region'] if latest else None)
            settings = single_region(settings, region or 'TR')
            db.execute('INSERT INTO tasks_v2 VALUES(?,?,?,?,?,?,?,?,NULL)',
                       (row['id'],row['owner_user_id'],row['jira_id'],row['title'],row['created_at'],row['updated_at'],json.dumps(settings,ensure_ascii=False),region))
        db.execute('DROP TABLE tasks')
        db.execute('ALTER TABLE tasks_v2 RENAME TO tasks')
        db.execute('CREATE INDEX tasks_owner_updated ON tasks(owner_user_id,updated_at DESC)')
        db.execute('''CREATE TABLE user_counters (
            user_id INTEGER PRIMARY KEY REFERENCES users(id), unnamed_task INTEGER NOT NULL DEFAULT 0)''')
        db.execute('''CREATE TABLE test_accounts (
            id TEXT PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            name TEXT NOT NULL, account_id TEXT NOT NULL, login TEXT NOT NULL, password TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('main','usd'))
        )''')
        db.execute('CREATE INDEX accounts_task ON test_accounts(task_id)')
        db.execute('ALTER TABLE test_cases ADD COLUMN test_account_id TEXT REFERENCES test_accounts(id) ON DELETE SET NULL')
        db.execute('ALTER TABLE test_cases ADD COLUMN client_key TEXT')
        db.execute('CREATE UNIQUE INDEX case_client_key ON test_cases(set_id,client_key)')
        db.execute('ALTER TABLE case_sets ADD COLUMN generation_key TEXT')
        db.execute('CREATE UNIQUE INDEX set_generation ON case_sets(task_id,generation_key)')
        for row in db.execute('SELECT id,region,settings FROM case_sets').fetchall():
            settings = single_region(json.loads(row['settings']),row['region'])
            db.execute('UPDATE case_sets SET settings=? WHERE id=?',(json.dumps(settings,ensure_ascii=False),row['id']))
        # Reinstall checks that refer to tasks after the table rebuild.
        for op in ('INSERT','UPDATE'):
            db.execute(f'''CREATE TRIGGER slack_link_owner_{op.lower()} BEFORE {op} ON slack_send_cases
                WHEN NOT EXISTS (SELECT 1 FROM slack_sends send JOIN test_cases c ON c.id=NEW.case_id
                    JOIN case_sets s ON s.id=c.set_id JOIN tasks t ON t.id=s.task_id
                    WHERE send.id=NEW.send_id AND send.owner_user_id=t.owner_user_id)
                BEGIN SELECT RAISE(ABORT,'Slack send and case owners differ'); END''')
            db.execute(f'''CREATE TRIGGER case_account_task_{op.lower()} BEFORE {op} ON test_cases
                WHEN NEW.test_account_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM test_accounts a JOIN case_sets s ON s.task_id=a.task_id
                    WHERE a.id=NEW.test_account_id AND s.id=NEW.set_id)
                BEGIN SELECT RAISE(ABORT,'Account belongs to a different task'); END''')
        db.execute('''CREATE TRIGGER tasks_owner_immutable BEFORE UPDATE OF owner_user_id ON tasks
            WHEN NEW.owner_user_id IS NOT OLD.owner_user_id
            BEGIN SELECT RAISE(ABORT,'Ownership transfer is not supported'); END''')
        db.execute('''CREATE TRIGGER accounts_task_immutable BEFORE UPDATE OF task_id ON test_accounts
            WHEN NEW.task_id IS NOT OLD.task_id
            BEGIN SELECT RAISE(ABORT,'Account transfer is not supported'); END''')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Workflow migration foreign key check failed')
        db.execute('PRAGMA user_version=2')
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
