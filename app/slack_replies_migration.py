"""Version 5: track Slack threads so replies can be attached to a case.

`slack_sends` already stored the body-message `ts` (for the permalink). To
follow a conversation we need the *parent* message of the thread and the
messages the application itself posted, so a reply can be told apart from our
own output without looking at the author (a QA engineer may later answer in
the same thread by hand).

New columns:
  slack_sends.thread_ts    parent message ts of the thread (body message parent)
  slack_sends.own_ts       JSON array of message ts values we posted in the thread
  slack_replies            one row per imported reply, unique per (send, ts)
"""
import json
import sqlite3
from app.ownership_migration import backup_database


def migrate(path, backup_existing):
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        columns = {row[1] for row in db.execute('PRAGMA table_info(slack_sends)')}
        replies_exist = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='slack_replies'"
        ).fetchone()

        # The version alone is not enough: a table recreated after a manual
        # DROP (or by an older build) can be missing the new columns while the
        # database already reports version 5. Converge on the actual schema.
        if version >= 5 and replies_exist and {'thread_ts', 'own_ts'} <= columns:
            db.rollback()
            return
        if version >= 5:
            # Schema repair: no data migration, so no backup is required.
            _apply_schema(db)
            db.commit()
            return

        if backup_existing:
            backup_database(path, 'pre-slack-replies')
        _apply_schema(db)
        db.execute('PRAGMA user_version=5')
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _apply_schema(db: sqlite3.Connection) -> None:
    """Add the reply-tracking columns and tables. Safe to run repeatedly."""
    columns = {row[1] for row in db.execute('PRAGMA table_info(slack_sends)')}
    if 'thread_ts' not in columns:
        db.execute('ALTER TABLE slack_sends ADD COLUMN thread_ts TEXT')
        # Historical rows only know the body message; it is its own thread
        # root from Slack's point of view when no parent was recorded.
        db.execute('UPDATE slack_sends SET thread_ts=ts WHERE thread_ts IS NULL')
    if 'own_ts' not in columns:
        db.execute("ALTER TABLE slack_sends ADD COLUMN own_ts TEXT NOT NULL DEFAULT '[]'")
        db.execute("UPDATE slack_sends SET own_ts=json_array(ts)")

    db.execute('''CREATE TABLE IF NOT EXISTS slack_replies (
        id INTEGER PRIMARY KEY,
        send_id INTEGER NOT NULL REFERENCES slack_sends(id) ON DELETE CASCADE,
        event_id TEXT,
        channel TEXT NOT NULL,
        thread_ts TEXT NOT NULL,
        ts TEXT NOT NULL,
        author_id TEXT,
        author_name TEXT,
        text TEXT NOT NULL DEFAULT '',
        received_at TEXT NOT NULL,
        UNIQUE(send_id, ts)
    )''')
    # Event deduplication: Slack retries deliveries, so an event_id may only
    # be processed once.
    db.execute('''CREATE TABLE IF NOT EXISTS slack_events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        received_at TEXT NOT NULL,
        outcome TEXT NOT NULL
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS replies_send ON slack_replies(send_id)')
    db.execute('CREATE INDEX IF NOT EXISTS replies_thread ON slack_replies(channel, thread_ts)')
    db.execute('CREATE INDEX IF NOT EXISTS sends_thread ON slack_sends(channel, thread_ts)')

    if db.execute('PRAGMA foreign_key_check').fetchall():
        raise RuntimeError('Slack replies migration foreign key check failed')
