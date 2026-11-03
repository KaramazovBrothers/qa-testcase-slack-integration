"""Schema v8: cache Slack member display names.

The workspace shows people by name, but Slack only guarantees an ID. Asking
`users.info` on every render would be slow and would break the UI whenever
Slack is unreachable, so names live in `slack_people` and are refreshed
lazily by `app/slack_people.py`.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 8


def migrate(path: Path, backup_existing) -> None:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        current = db.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{current} is newer than this code (v{SCHEMA_VERSION})"
            )

        has_table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='slack_people'"
        ).fetchone() is not None

        if current >= SCHEMA_VERSION and has_table:
            return

        if backup_existing:
            from app.ownership_migration import backup_database

            backup_database(path, label=f"pre-v{SCHEMA_VERSION}")

        # No foreign key to users: the same Slack person may be mentioned by
        # several workspace users, and a name is valid without an owner.
        db.execute(
            """CREATE TABLE IF NOT EXISTS slack_people (
                slack_user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                team_id TEXT,
                fetched_at TEXT NOT NULL
            )"""
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS people_name ON slack_people(name COLLATE NOCASE)"
        )
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
    finally:
        db.close()
