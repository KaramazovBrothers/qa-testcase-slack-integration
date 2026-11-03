"""Schema v6: persist the Slack user token so it survives restarts.

Before v6 the token lived in a module-level variable, so every uvicorn restart
forced a fresh OAuth round-trip. The token is now stored per user in
`users.slack_token`; the database file is already 0600 and git-ignored.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 6
# Any later migration means a database that already has this column.
LATEST_SCHEMA_VERSION = 11


def migrate(path: Path, backup_existing) -> None:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        current = db.execute("PRAGMA user_version").fetchone()[0]
        if current > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{current} is newer than this code (v{LATEST_SCHEMA_VERSION})"
            )

        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        has_column = "slack_token" in columns

        if current < SCHEMA_VERSION or not has_column:
            if backup_existing:
                from app.ownership_migration import backup_database

                backup_database(path, label=f"pre-v{SCHEMA_VERSION}")
            if not has_column:
                # The column may legitimately be missing when `users` was
                # recreated, so the check is on the column and not only on the
                # stored version.
                db.execute("ALTER TABLE users ADD COLUMN slack_token TEXT")
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            db.commit()
    finally:
        db.close()
