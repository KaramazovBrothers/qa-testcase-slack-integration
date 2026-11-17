"""One connection layer for both engines.

The rest of the application keeps using `storage.connection()` and plain SQL.
This module provides the PostgreSQL flavour of that same object: `?`
placeholders, `cursor.lastrowid` after an INSERT, `rowcount`, `INSERT OR IGNORE`
and `BEGIN IMMEDIATE`. Without `QAHELPER_DATABASE_URL` everything stays on the
local SQLite file, exactly as before.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

SQLITE = "sqlite"
POSTGRES = "postgres"

_ENGINE_OVERRIDE: Optional[str] = None

# SQLite-only phrases the shared SQL uses, and what PostgreSQL needs instead.
_REWRITES = (
    ("INSERT OR IGNORE INTO", "INSERT INTO"),
    ("INSERT OR REPLACE INTO", "INSERT INTO"),
    ("BEGIN IMMEDIATE", "BEGIN"),
    ("DATETIME('NOW')", "to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')"),
    ("datetime('now')", "to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')"),
)


class Row:
    """Result row that behaves like sqlite3.Row (name and index access)."""

    __slots__ = ("_data", "_order")

    def __init__(self, data):
        self._data = dict(data)
        self._order = list(data.keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[self._order[key]]
        return self._data[key]

    def keys(self):
        return list(self._order)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def items(self):
        return ((name, self._data[name]) for name in self._order)

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._order)

    def __len__(self):
        return len(self._order)

    def __eq__(self, other):
        return self._data == other

    def __repr__(self):
        return f"Row({self._data!r})"


def database_url() -> str:
    return (os.getenv("QAHELPER_DATABASE_URL") or "").strip()


def engine() -> str:
    # `set_engine()` lets tests point the same code at a throwaway database.
    return _ENGINE_OVERRIDE or (POSTGRES if database_url() else SQLITE)


def set_engine(name: Optional[str]) -> None:
    """Force an engine (or clear the override with None)."""
    global _ENGINE_OVERRIDE
    _ENGINE_OVERRIDE = name


def connect_url(url: str):
    """Open one explicit URL, bypassing the module-wide engine choice."""
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(url, row_factory=dict_row, autocommit=False)


def adapt(sql: str) -> str:
    """Translate the statements the shared code writes for SQLite."""
    text = sql
    for old, new in _REWRITES:
        text = text.replace(old, new)
    # `INSERT OR IGNORE` becomes ON CONFLICT DO NOTHING when the statement does
    # not already carry an explicit conflict target.
    if sql.strip().upper().startswith("INSERT OR IGNORE") and "ON CONFLICT" not in text.upper():
        text = text.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return text


class Cursor:
    """The subset of sqlite3.Cursor the application relies on."""

    def __init__(self, cursor, lastrowid: Optional[int] = None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._cursor.close()
        return False

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def _wrap(self, row):
        # sqlite3.Row supports both row["name"] and row[0]; psycopg dict_row
        # only supports the first, so rows are given the sqlite behaviour.
        if row is None or isinstance(row, (sqlite3.Row, Row)):
            return row
        if isinstance(row, dict):
            return Row(row)
        return row

    def fetchone(self):
        return self._wrap(self._cursor.fetchone())

    def fetchall(self):
        return [self._wrap(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return iter([self._wrap(row) for row in self._cursor])


class PostgresConnection:
    """sqlite3.Connection-compatible wrapper over psycopg."""

    def __init__(self, raw):
        from psycopg.rows import dict_row

        self._raw = raw
        self._dict_row = dict_row

    # -- statements ---------------------------------------------------------
    def execute(self, sql: str, params=()):
        """Run one statement.

        `params` may be given even when the SQL has no `?` (the shared code
        often passes a tuple built for a longer variant); psycopg rejects a
        mismatched count, so the parameters are used only when they can be
        matched to the placeholders the statement actually has.
        """
        text = adapt(sql)
        values = tuple(params) if params else ()
        slots = text.count("?")
        if slots and len(values) != slots:
            raise ValueError(f"SQL expects {slots} parameters, got {len(values)}")
        if slots:
            text = text.replace("?", "%s")
        else:
            values = ()
        returns_id = text.lstrip().upper().startswith("INSERT") and "RETURNING" not in text.upper()
        if returns_id:
            text = text.rstrip().rstrip(";") + " RETURNING id"
        cursor = self._raw.cursor(row_factory=self._dict_row)
        cursor.execute(text, values or None)
        lastrowid = None
        if returns_id:
            row = cursor.fetchone()
            lastrowid = next(iter(row.values())) if row else None
        return Cursor(cursor, lastrowid)

    def executemany(self, sql: str, rows):
        cursor = self._raw.cursor()
        cursor.executemany(adapt(sql).replace("?", "%s"), list(rows))
        return Cursor(cursor)

    def executescript(self, script: str):
        raise NotImplementedError("PostgreSQL schema is created from app.pg_schema")

    # -- transaction --------------------------------------------------------
    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    @property
    def row_factory(self):
        return self._dict_row


@contextmanager
def connection(url: Optional[str] = None) -> Iterator[object]:
    """Same contract as `storage.connection`: commit on success, close always.

    `url` (used by tests) targets a specific database instead of the one from
    the environment.
    """
    import psycopg

    raw = psycopg.connect(url or database_url(), autocommit=False)
    wrapped = PostgresConnection(raw)
    try:
        with raw:  # commits on clean exit, rolls back on an exception
            yield wrapped
    finally:
        raw.close()


def sqlite_connection(path):
    """The original SQLite connection, untouched by the adapter."""
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db
