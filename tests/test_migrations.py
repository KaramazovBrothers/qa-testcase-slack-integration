"""Schema upgrades must never lose work.

Every migration runs on startup against a database that already holds real
cases, and none of them was covered by a test. A silent `ALTER TABLE` gone
wrong is the one bug the operator cannot undo, so each check here is about
data surviving the upgrade, not about the SQL being pretty.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import storage
from app import task_status_migration, webview_apk_migration


def _columns(path: Path, table: str) -> set[str]:
    db = sqlite3.connect(path)
    try:
        return {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
    finally:
        db.close()


def _version(path: Path) -> int:
    db = sqlite3.connect(path)
    try:
        return db.execute('PRAGMA user_version').fetchone()[0]
    finally:
        db.close()


class TaskStatusMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'qa.db'

    def _old_database(self):
        """A v9 database: tasks exist, the status column does not."""
        db = sqlite3.connect(self.path)
        try:
            db.execute(
                'CREATE TABLE tasks (id INTEGER PRIMARY KEY, owner_user_id INTEGER,'
                ' jira_id TEXT, title TEXT, settings TEXT, updated_at TEXT)'
            )
            db.execute(
                "INSERT INTO tasks (owner_user_id, jira_id, title, settings, updated_at)"
                " VALUES (1, 'QA-1', 'Existing task', '{}', '2026-01-01T00:00:00+00:00')"
            )
            db.execute('PRAGMA user_version = 9')
            db.commit()
        finally:
            db.close()

    def test_adds_status_and_keeps_existing_rows(self):
        self._old_database()
        task_status_migration.migrate(self.path, backup_existing=False)

        self.assertIn('status', _columns(self.path, 'tasks'))
        db = sqlite3.connect(self.path)
        try:
            rows = list(db.execute('SELECT jira_id, title, status FROM tasks'))
        finally:
            db.close()
        # Existing work stays listed instead of disappearing behind a filter.
        self.assertEqual(rows, [('QA-1', 'Existing task', 'active')])
        self.assertEqual(_version(self.path), task_status_migration.SCHEMA_VERSION)

    def test_second_run_is_a_no_op(self):
        self._old_database()
        task_status_migration.migrate(self.path, backup_existing=False)
        before = self.path.stat().st_mtime_ns
        task_status_migration.migrate(self.path, backup_existing=False)

        db = sqlite3.connect(self.path)
        try:
            count = db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        finally:
            db.close()
        self.assertEqual(count, 1)
        self.assertEqual(_version(self.path), task_status_migration.SCHEMA_VERSION)
        self.assertGreaterEqual(self.path.stat().st_mtime_ns, before)

    def test_refuses_a_database_from_the_future(self):
        self._old_database()
        db = sqlite3.connect(self.path)
        try:
            db.execute(f'PRAGMA user_version = {task_status_migration.LATEST_SCHEMA_VERSION + 5}')
            db.commit()
        finally:
            db.close()
        # Downgrading silently would corrupt columns this code cannot know about.
        with self.assertRaises(RuntimeError):
            task_status_migration.migrate(self.path, backup_existing=False)


class WebviewApkMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'qa.db'
        db = sqlite3.connect(self.path)
        try:
            db.execute(
                'CREATE TABLE tasks (id INTEGER PRIMARY KEY, owner_user_id INTEGER,'
                ' jira_id TEXT, title TEXT, settings TEXT, updated_at TEXT)'
            )
            db.execute(
                "INSERT INTO tasks (owner_user_id, jira_id, title, settings, updated_at)"
                " VALUES (1, 'QA-2', 'Kept', '{}', '2026-01-01T00:00:00+00:00')"
            )
            db.commit()
        finally:
            db.close()

    def test_creates_the_apk_table_without_touching_tasks(self):
        webview_apk_migration.migrate(self.path, backup_existing=False)

        db = sqlite3.connect(self.path)
        try:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            rows = list(db.execute('SELECT jira_id, title FROM tasks'))
        finally:
            db.close()
        self.assertIn('webview_apks', tables)
        self.assertEqual(rows, [('QA-2', 'Kept')])

    def test_second_run_is_a_no_op(self):
        webview_apk_migration.migrate(self.path, backup_existing=False)
        webview_apk_migration.migrate(self.path, backup_existing=False)

        db = sqlite3.connect(self.path)
        try:
            count = db.execute('SELECT COUNT(*) FROM webview_apks').fetchone()[0]
        finally:
            db.close()
        self.assertEqual(count, 0)


class FullStartupTests(unittest.TestCase):
    """The real entry point: every migration runs in order on one database."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'qa.db'
        self.enterContext(
            patch.object(storage, 'DB_PATH', self.path)
        )

    def test_initialize_twice_keeps_data_and_version(self):
        storage.initialize()
        version = _version(self.path)

        db = sqlite3.connect(self.path)
        try:
            db.execute(
                "INSERT INTO tasks (owner_user_id, jira_id, title, settings, created_at, updated_at, status)"
                " VALUES (1, 'QA-3', 'Survivor', '{}', '2026-01-01T00:00:00+00:00',"
                " '2026-01-01T00:00:00+00:00', 'active')"
            )
            db.commit()
        finally:
            db.close()

        # A restart must not drop the work of the previous run.
        storage.initialize()

        db = sqlite3.connect(self.path)
        try:
            rows = list(db.execute("SELECT jira_id, title FROM tasks WHERE jira_id='QA-3'"))
        finally:
            db.close()
        self.assertEqual(rows, [('QA-3', 'Survivor')])
        self.assertEqual(_version(self.path), version)


if __name__ == '__main__':
    unittest.main()
