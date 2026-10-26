"""Local, transactional SQLite storage. No Slack tokens are persisted here."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

LOCAL_USER_ID = 1

DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'qa_tests.db'


@contextmanager
def connection():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    backup_existing = DB_PATH.exists() and DB_PATH.stat().st_size > 0
    DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Create the file with private permissions from its first byte.
    fd = os.open(DB_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    DB_PATH.chmod(0o600)
    with connection() as db:
        from app.ownership_migration import SCHEMA_VERSION
        if db.execute('PRAGMA user_version').fetchone()[0] > SCHEMA_VERSION:
            raise RuntimeError('Database schema is newer than this application')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY, jira_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
            title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            settings TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS case_sets (
            id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            name TEXT NOT NULL, created_at TEXT NOT NULL, settings TEXT NOT NULL,
            region TEXT NOT NULL, operation TEXT NOT NULL, mention_users TEXT
        );
        CREATE INDEX IF NOT EXISTS sets_task ON case_sets(task_id);
        CREATE TABLE IF NOT EXISTS test_cases (
            id INTEGER PRIMARY KEY, set_id INTEGER NOT NULL REFERENCES case_sets(id) ON DELETE CASCADE,
            position INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL,
            comment TEXT NOT NULL DEFAULT '', request_text TEXT,
            status TEXT NOT NULL DEFAULT 'Not tested'
                CHECK(status IN ('Not tested','Passed','Failed','Blocked','Skipped')),
            qa_comment TEXT NOT NULL DEFAULT '', bug_links TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL, UNIQUE(set_id, position)
        );
        CREATE INDEX IF NOT EXISTS cases_set ON test_cases(set_id);
        CREATE TABLE IF NOT EXISTS slack_sends (
            id INTEGER PRIMARY KEY,
            channel TEXT NOT NULL, ts TEXT NOT NULL, sent_at TEXT NOT NULL,
            permalink TEXT, permalink_error TEXT,
            permalink_checked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS slack_send_cases (
            send_id INTEGER NOT NULL REFERENCES slack_sends(id) ON DELETE CASCADE,
            case_id INTEGER NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
            PRIMARY KEY(send_id, case_id)
        );
        CREATE INDEX IF NOT EXISTS slack_send_cases_case ON slack_send_cases(case_id);
        CREATE TRIGGER IF NOT EXISTS delete_unlinked_slack_send
        AFTER DELETE ON slack_send_cases
        BEGIN
            DELETE FROM slack_sends WHERE id=OLD.send_id
              AND NOT EXISTS (SELECT 1 FROM slack_send_cases WHERE send_id=OLD.send_id);
        END;

        ''')
    from app.ownership_migration import migrate
    migrate(DB_PATH, backup_existing)
    from app.workflow_migration import migrate as migrate_workflow
    migrate_workflow(DB_PATH, backup_existing)
    from app.region_accounts_migration import migrate as migrate_accounts
    migrate_accounts(DB_PATH, backup_existing)
    from app.single_set_migration import migrate as migrate_single_set
    migrate_single_set(DB_PATH, backup_existing)
    DB_PATH.chmod(0o600)


def decode(row, *fields):
    result = dict(row)
    for field in fields:
        result[field] = json.loads(result[field]) if result[field] is not None else None
    return result
