"""Slack people directory schema (v8 -> v9).

v8 cached whatever `users.info` returned. v9 makes the list a shared, maintained
directory: each person belongs to one region, so "Восстановить список региона"
can reload it. The table is rebuilt because SQLite cannot add a NOT NULL column
without a default; existing names survive and land in `region = ''`.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 9


def migrate(path: Path, backup_existing) -> None:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        current = db.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{current} is newer than this code (v{SCHEMA_VERSION})"
            )

        columns = {row["name"] for row in db.execute("PRAGMA table_info(slack_people)")}
        has_table = bool(columns)

        if current >= SCHEMA_VERSION and "region" in columns:
            return

        if backup_existing:
            from app.ownership_migration import backup_database

            backup_database(path, label=f"pre-v{SCHEMA_VERSION}")

        db.execute(
            """CREATE TABLE IF NOT EXISTS slack_people_v9 (
                slack_user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                team_id TEXT,
                region TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )"""
        )
        if has_table:
            # v8 rows have no region; keep the name so nothing is lost.
            db.execute(
                """INSERT OR IGNORE INTO slack_people_v9
                       (slack_user_id, name, team_id, region, fetched_at, updated_at)
                   SELECT slack_user_id, coalesce(name, ''), team_id, '',
                          coalesce(fetched_at, ''), coalesce(fetched_at, '')
                   FROM slack_people"""
            )
        db.execute("DROP TABLE IF EXISTS slack_people")
        db.execute("ALTER TABLE slack_people_v9 RENAME TO slack_people")
        db.execute("CREATE INDEX IF NOT EXISTS people_region ON slack_people(region)")
        db.execute("CREATE INDEX IF NOT EXISTS people_name ON slack_people(name COLLATE NOCASE)")
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
    finally:
        db.close()
