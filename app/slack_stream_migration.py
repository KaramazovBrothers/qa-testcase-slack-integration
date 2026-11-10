"""Reply replay table (v11 -> v12).

Live replies used to travel only through an in-process queue. Behind a reverse
proxy the app can run more than one worker, and Slack posts an event to
whichever worker it reaches, so the tab connected elsewhere never learned about
the reply. Filing each published event for a short replay window lets any
worker serve a stream that catches up on connect.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 12
LATEST_SCHEMA_VERSION = 13


def migrate(path: Path, backup_existing) -> None:
    db = sqlite3.connect(path)
    try:
        current = db.execute("PRAGMA user_version").fetchone()[0]
        if current > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{current} is newer than this code (v{LATEST_SCHEMA_VERSION})"
            )
        if current >= SCHEMA_VERSION:
            return

        if backup_existing:
            from app.ownership_migration import backup_database

            backup_database(path, label=f"pre-v{SCHEMA_VERSION}")

        db.execute(
            """CREATE TABLE IF NOT EXISTS slack_stream_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS stream_events_created ON slack_stream_events(created_at)"
        )
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
    finally:
        db.close()
