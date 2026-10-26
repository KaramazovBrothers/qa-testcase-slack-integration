"""Transactional upgrade from the single-QA schema; preserves all row IDs."""
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = 4


def backup_database(db_path, label='pre-users'):
    folder = db_path.parent / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = folder / f'{db_path.stem}.{label}.{stamp}.db'
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source = sqlite3.connect(db_path)
    backup = sqlite3.connect(target)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()
    return target


def migrate(db_path, backup_existing):
    db = sqlite3.connect(db_path, timeout=10)
    try:
        # SQLite requires foreign keys OFF outside the transaction to rebuild
        # the tasks UNIQUE constraint without deleting its children.
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError('Database schema is newer than this application')
        needs_tasks = 'owner_user_id' not in {r[1] for r in db.execute('PRAGMA table_info(tasks)')}
        if needs_tasks and backup_existing:
            # A separate read connection can back up the last committed state
            # while this connection holds the writer reservation.
            backup_database(db_path)
        stamp = datetime.now(timezone.utc).isoformat()
        db.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            auth_provider TEXT NOT NULL,
            auth_subject TEXT NOT NULL,
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(auth_provider, auth_subject)
        )''')
        db.execute('''INSERT OR IGNORE INTO users
            (id,auth_provider,auth_subject,display_name,created_at,updated_at)
            VALUES(1,'local','local-qa','Local QA',?,?)''', (stamp, stamp))
        if db.execute('SELECT auth_provider,auth_subject FROM users WHERE id=1').fetchone() != ('local','local-qa'):
            raise RuntimeError('Reserved local user identity mismatch')
        if needs_tasks:
            db.execute('''CREATE TABLE tasks_with_owner (
                id INTEGER PRIMARY KEY,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                jira_id TEXT NOT NULL COLLATE NOCASE,
                title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                settings TEXT NOT NULL DEFAULT '{}',
                UNIQUE(owner_user_id,jira_id)
            )''')
            db.execute('''INSERT INTO tasks_with_owner
                (id,owner_user_id,jira_id,title,created_at,updated_at,settings)
                SELECT id,1,jira_id,title,created_at,updated_at,settings FROM tasks''')
            db.execute('DROP TABLE tasks')
            db.execute('ALTER TABLE tasks_with_owner RENAME TO tasks')
        if 'owner_user_id' not in {r[1] for r in db.execute('PRAGMA table_info(slack_sends)')}:
            db.execute('ALTER TABLE slack_sends ADD COLUMN owner_user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id) ON DELETE RESTRICT')
        db.execute('CREATE INDEX IF NOT EXISTS tasks_owner_updated ON tasks(owner_user_id,updated_at DESC)')
        db.execute('CREATE INDEX IF NOT EXISTS slack_sends_owner ON slack_sends(owner_user_id)')
        # Ownership is inherited by settings, sets, cases and QA results through
        # the task. Cross-user shared Slack links must never join those trees.
        for operation in ('INSERT','UPDATE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS slack_link_owner_{operation.lower()}
                BEFORE {operation} ON slack_send_cases
                WHEN NOT EXISTS (
                    SELECT 1 FROM slack_sends send
                    JOIN test_cases c ON c.id=NEW.case_id
                    JOIN case_sets s ON s.id=c.set_id
                    JOIN tasks t ON t.id=s.task_id
                    WHERE send.id=NEW.send_id AND send.owner_user_id=t.owner_user_id
                )
                BEGIN SELECT RAISE(ABORT,'Slack send and case owners differ'); END''')
        # No ownership transfer API exists. Prevent moving any tree node from
        # underneath an existing history link by ad hoc database updates.
        for table, column in (('tasks','owner_user_id'), ('slack_sends','owner_user_id'),
                              ('case_sets','task_id'), ('test_cases','set_id')):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_owner_immutable
                BEFORE UPDATE OF {column} ON {table}
                WHEN NEW.{column} IS NOT OLD.{column}
                BEGIN SELECT RAISE(ABORT,'Ownership transfer is not supported'); END''')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Foreign key check failed; ownership migration rolled back')
        db.execute(f'PRAGMA user_version={max(version, 1)}')
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
