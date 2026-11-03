"""Schema v7: per-user Slack OAuth state and token metadata.

Before v7 the OAuth `state` values lived in a process-local set, so a restart
or a second worker invalidated an in-flight authorization and two concurrent
users could not be told apart. State is now a database row bound to the user
who started the flow, with an expiry.

`slack_token` already exists per user (v6). This migration adds the columns
that let the UI tell users apart: the Slack user id, the team id and the
granted scopes, plus when the token was issued.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 7
# Any later migration means a database that already has this table.
LATEST_SCHEMA_VERSION = 8

OAUTH_STATE_TTL_SECONDS = 600


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
        user_columns = {
            "slack_user_id": "TEXT",
            "slack_team_id": "TEXT",
            "slack_scopes": "TEXT",
            "slack_token_issued_at": "TEXT",
        }
        missing = {name: kind for name, kind in user_columns.items() if name not in columns}

        has_states = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='slack_oauth_states'"
        ).fetchone() is not None

        if current >= SCHEMA_VERSION and not missing and has_states:
            return

        if backup_existing:
            from app.ownership_migration import backup_database

            backup_database(path, label=f"pre-v{SCHEMA_VERSION}")

        for name, kind in missing.items():
            db.execute(f"ALTER TABLE users ADD COLUMN {name} {kind}")

        # An OAuth state is single-use, tied to the initiating user and expires.
        db.execute(
            """CREATE TABLE IF NOT EXISTS slack_oauth_states (
                state TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )"""
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS oauth_states_expiry ON slack_oauth_states(expires_at)"
        )
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
    finally:
        db.close()


def issue_state(path: Path, user_id: int, state: str) -> None:
    """Record a fresh authorization attempt for one user."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS)
    db = sqlite3.connect(path)
    try:
        with db:
            db.execute("DELETE FROM slack_oauth_states WHERE expires_at < ?", (now.isoformat(),))
            db.execute(
                "INSERT INTO slack_oauth_states(state,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                (state, user_id, now.isoformat(), expires.isoformat()),
            )
    finally:
        db.close()


def consume_state(path: Path, state: str) -> int | None:
    """Return the user the state belongs to and delete it.

    A state is single use: consuming it before the token exchange means a
    replay of the same callback URL cannot bind a second token.
    """
    now = datetime.now(timezone.utc).isoformat()
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        with db:
            row = db.execute(
                "SELECT user_id, expires_at FROM slack_oauth_states WHERE state=?",
                (state,),
            ).fetchone()
            db.execute("DELETE FROM slack_oauth_states WHERE state=?", (state,))
        if row is None or row["expires_at"] < now:
            return None
        return int(row["user_id"])
    finally:
        db.close()
