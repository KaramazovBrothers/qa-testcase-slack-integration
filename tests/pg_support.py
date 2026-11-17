"""Run the suite against PostgreSQL as well as SQLite.

Set `QAHELPER_TEST_DATABASE_URL` (for example
`postgresql:///qahelper_test?host=/tmp` or `postgresql:///qahelper_test`) and
every test class that mixes in `EngineTestCase` gets a private schema in that
database: created before the test, dropped after it. Without the variable the
classes behave exactly as before (a temporary SQLite file per test).
"""

import os
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app import storage

TEST_URL = (os.getenv('QAHELPER_TEST_DATABASE_URL') or '').strip()


@contextmanager
def scratch_database():
    """A private SQLite file, or a private schema in the test database."""
    if not TEST_URL:
        temp = tempfile.TemporaryDirectory()
        try:
            yield Path(temp.name) / 'data' / 'qa_tests.db'
        finally:
            temp.cleanup()
        return

    import psycopg
    schema = 'test_' + uuid.uuid4().hex[:12]
    admin = psycopg.connect(TEST_URL, autocommit=True)
    admin.execute(f'CREATE SCHEMA "{schema}"')
    admin.close()
    sep = '&' if '?' in TEST_URL else '?'
    url = f'{TEST_URL}{sep}options=-csearch_path%3D{schema}'
    try:
        yield url
    finally:
        admin = psycopg.connect(TEST_URL, autocommit=True)
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()


class EngineTestCase(unittest.TestCase):
    """Give each test its own database on the engine under test.

    Subclasses keep patching `storage.DB_PATH` if they like; in Postgres mode
    the patch is harmless because the connection ignores the file.
    """

    def setUp(self):
        # Registered on the unittest exit stack: subclasses that call
        # `enterContext` themselves then unwind in the correct order, and the
        # scratch database still disappears if a subclass setUp fails.
        self._db_patch = self.enterContext(scratch_environment())
        super().setUp()


@contextmanager
def scratch_environment():
    """Bind `storage` to a scratch database for the duration of one test."""
    with scratch_database() as target:
        storage.use_database_url(target if isinstance(target, str) else None)
        patcher = patch.object(storage, 'DB_PATH', target)
        patcher.start()
        try:
            yield patcher
        finally:
            patcher.stop()
            storage.use_database_url(None)
