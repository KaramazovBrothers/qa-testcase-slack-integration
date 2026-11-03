"""WebView APK library and the people asked for a fresh build (v10 -> v11).

Testers on mobile need the WebView build of an app, not only the store one.
The binaries are shared by everyone, so they live in one table keyed by
licence, and each upload replaces the previous file for that licence: the
build a tester downloads is always the latest one.

The channel that receives "send a fresh build" requests needs its own list of
people. That list is per channel, not per region, so it gets its own table
rather than sharing the region-keyed `slack_people` directory.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 11

CHANNEL = "C07RKCUN132"
DEFAULT_MEMBER = ("U03V08KDU31", "Denys Denysenko")


def migrate(path: Path, backup_existing) -> None:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        current = db.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{current} is newer than this code (v{SCHEMA_VERSION})"
            )
        if current >= SCHEMA_VERSION:
            return

        if backup_existing:
            from app.ownership_migration import backup_database

            backup_database(path, label=f"pre-v{SCHEMA_VERSION}")

        db.execute(
            """CREATE TABLE IF NOT EXISTS webview_apks (
                licence TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                content BLOB NOT NULL,
                uploaded_at TEXT NOT NULL,
                uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS channel_people (
                channel TEXT NOT NULL,
                slack_user_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (channel, slack_user_id)
            )"""
        )
        # The person who maintains the builds is in the list from day one.
        db.execute(
            """INSERT OR IGNORE INTO channel_people(channel,slack_user_id,name,created_at)
               VALUES(?,?,?,datetime('now'))""",
            (CHANNEL, DEFAULT_MEMBER[0], DEFAULT_MEMBER[1]),
        )
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
    finally:
        db.close()
