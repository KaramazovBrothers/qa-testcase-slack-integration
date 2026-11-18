"""The SQLite/PostgreSQL adapter must serve both schema shapes.

`slack_events` has no `id` column (its key is `event_id`). The adapter used to
append `RETURNING id` to *every* INSERT, so a PostgreSQL write to that table
failed and the import silently lost rows. These tests keep that fixed.
"""

import unittest

from app import storage
from tests.pg_support import EngineTestCase


class AdapterContractTests(EngineTestCase):
    def test_insert_into_table_without_id_column(self):
        storage.initialize()
        with storage.connection() as db:
            db.execute(
                'INSERT INTO slack_events(event_id,event_type,received_at,outcome) VALUES(?,?,?,?)',
                ('Ev-test-1', 'message', '2026-11-18T00:00:00+00:00', 'stored'),
            )
            row = db.execute(
                'SELECT event_id, outcome FROM slack_events WHERE event_id=?',
                ('Ev-test-1',),
            ).fetchone()
        self.assertIsNotNone(row, 'the row must be readable after the insert')
        self.assertEqual(row['event_id'], 'Ev-test-1')
        self.assertEqual(row[1], 'stored', 'positional access must work too')

    def test_insert_into_table_with_id_column_reports_lastrowid(self):
        storage.initialize()
        with storage.connection() as db:
            cursor = db.execute(
                'INSERT INTO tasks(owner_user_id,jira_id,title,status,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?)',
                (1, 'QA-ADA-1', 'adapter', 'active', 'now', 'now'),
            )
            self.assertIsNotNone(cursor.lastrowid, 'id must come back from the INSERT')
            new_id = cursor.lastrowid
            found = db.execute('SELECT jira_id FROM tasks WHERE id=?', (new_id,)).fetchone()
        self.assertEqual(found['jira_id'], 'QA-ADA-1')

    def test_insert_or_ignore_is_idempotent(self):
        storage.initialize()
        statement = ('INSERT OR IGNORE INTO slack_stream_events(event_id,payload,created_at) '
                     'VALUES(?,?,?)')
        with storage.connection() as db:
            db.execute(statement, ('Ev-dup', '{"a":1}', '2026-11-18T00:00:00+00:00'))
            db.execute(statement, ('Ev-dup', '{"a":2}', '2026-11-18T00:00:01+00:00'))
            rows = db.execute(
                'SELECT payload FROM slack_stream_events WHERE event_id=?', ('Ev-dup',)
            ).fetchall()
        self.assertEqual(len(rows), 1, 'the duplicate must be ignored')
        self.assertEqual(rows[0]['payload'], '{"a":1}')


if __name__ == '__main__':
    unittest.main()
