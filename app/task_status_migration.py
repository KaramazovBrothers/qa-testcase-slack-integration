"""Task status column (v9 -> v10).

Tasks are either actively worked on or finished. The flag is stored so the
sidebar can hide finished work, and it defaults to 'active' so every existing
task stays visible after the upgrade.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 10
LATEST_SCHEMA_VERSION = 11
ACTIVE = 'active'
DONE = 'done'


def migrate(path: Path, backup_existing) -> None:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        current = db.execute("PRAGMA user_version").fetchone()[0]
        if current > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{current} is newer than this code (v{SCHEMA_VERSION})"
            )

        columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
        if "status" in columns:
            if current < SCHEMA_VERSION:
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                db.commit()
            return

        if backup_existing:
            from app.ownership_migration import backup_database

            backup_database(path, label=f"pre-v{SCHEMA_VERSION}")

        # Existing tasks are in flight, so the default keeps them listed.
        db.execute(
            f"ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT '{ACTIVE}'"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS tasks_owner_status ON tasks(owner_user_id,status,updated_at DESC)"
        )
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
    finally:
        db.close()
