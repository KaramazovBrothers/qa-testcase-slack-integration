"""Screenshots of how a payment method looks on the frontend (v12 -> v13).

A case can show the tester what the method looks like. One picture is uploaded
per set and applied to every generated case; a case may override it with its
own picture. Changing the set picture only changes the default, so per-case
overrides survive a re-upload.

`test_cases.image_id` references a row in `case_images`; deleting a picture that
a case still uses is refused by the foreign key, so a delivered image never
disappears from under a case.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 13
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
            """CREATE TABLE IF NOT EXISTS case_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                set_id INTEGER REFERENCES case_sets(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                media_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                content BLOB NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        # One default picture per set: re-uploading replaces it in place.
        db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS case_images_default
               ON case_images(set_id) WHERE is_default=1"""
        )
        db.execute("CREATE INDEX IF NOT EXISTS case_images_owner ON case_images(owner_user_id)")
        # A database migrated by an interrupted run may already have the column.
        columns = {row[1] for row in db.execute("PRAGMA table_info(test_cases)")}
        if "image_id" not in columns:
            db.execute("ALTER TABLE test_cases ADD COLUMN image_id INTEGER "
                       "REFERENCES case_images(id) ON DELETE RESTRICT")
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
    finally:
        db.close()
