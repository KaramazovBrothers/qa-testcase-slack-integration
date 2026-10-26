
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY, jira_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
            title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            settings TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS case_sets (
            id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            name TEXT NOT NULL, created_at TEXT NOT NULL, settings TEXT NOT NULL,
            region TEXT NOT NULL, operation TEXT NOT NULL, mention_users TEXT
        );
        CREATE INDEX IF NOT EXISTS sets_task ON case_sets(task_id);
        CREATE TABLE IF NOT EXISTS test_cases (
            id INTEGER PRIMARY KEY, set_id INTEGER NOT NULL REFERENCES case_sets(id) ON DELETE CASCADE,
            position INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL,
            comment TEXT NOT NULL DEFAULT '', request_text TEXT,
            status TEXT NOT NULL DEFAULT 'Not tested'
                CHECK(status IN ('Not tested','Passed','Failed','Blocked','Skipped')),
            qa_comment TEXT NOT NULL DEFAULT '', bug_links TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL, UNIQUE(set_id, position)
        );
        CREATE INDEX IF NOT EXISTS cases_set ON test_cases(set_id);
        CREATE TABLE IF NOT EXISTS slack_sends (
            id INTEGER PRIMARY KEY,
            channel TEXT NOT NULL, ts TEXT NOT NULL, sent_at TEXT NOT NULL,
            permalink TEXT, permalink_error TEXT,
            permalink_checked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS slack_send_cases (
            send_id INTEGER NOT NULL REFERENCES slack_sends(id) ON DELETE CASCADE,
            case_id INTEGER NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
            PRIMARY KEY(send_id, case_id)
        );
        CREATE INDEX IF NOT EXISTS slack_send_cases_case ON slack_send_cases(case_id);
        CREATE TRIGGER IF NOT EXISTS delete_unlinked_slack_send
        AFTER DELETE ON slack_send_cases
        BEGIN
            DELETE FROM slack_sends WHERE id=OLD.send_id
              AND NOT EXISTS (SELECT 1 FROM slack_send_cases WHERE send_id=OLD.send_id);
        END;
