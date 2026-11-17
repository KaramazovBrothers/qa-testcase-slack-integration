"""Schema v13 for PostgreSQL, plus an import of the local SQLite file.

Until now the schema was built by replaying twelve SQLite migrations on start.
Postgres starts from this snapshot instead: one set of statements that create
exactly the same tables, and the same version number so the application code
does not need to know which engine it is talking to.

`import_sqlite` copies an existing `qa_tests.db` into the new database: every
table keeps its ids and timestamps, and booleans stored as 0/1 stay integers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def user_version(db) -> int:
    return db.execute("SELECT version FROM schema_version").fetchone()["version"]


def _safe(sql: str) -> str:
    return sql


CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
INSERT INTO schema_version(id, version) VALUES (1, 13) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    auth_provider TEXT NOT NULL,
    auth_subject TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    slack_token TEXT,
    slack_user_id TEXT,
    slack_team_id TEXT,
    slack_scopes TEXT,
    slack_token_issued_at TEXT,
    UNIQUE (auth_provider, auth_subject)
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    jira_id TEXT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}',
    region TEXT,
    client_key TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE (owner_user_id, jira_id),
    UNIQUE (owner_user_id, client_key)
);
CREATE INDEX IF NOT EXISTS tasks_owner_updated ON tasks(owner_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS tasks_owner_status ON tasks(owner_user_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS case_sets (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    settings TEXT NOT NULL,
    region TEXT NOT NULL,
    operation TEXT NOT NULL,
    mention_users TEXT,
    generation_key TEXT
);
CREATE INDEX IF NOT EXISTS sets_task ON case_sets(task_id);
CREATE UNIQUE INDEX IF NOT EXISTS one_set_per_task ON case_sets(task_id);
CREATE UNIQUE INDEX IF NOT EXISTS set_generation ON case_sets(task_id, generation_key);

CREATE TABLE IF NOT EXISTS test_accounts (
    id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    region TEXT NOT NULL,
    name TEXT NOT NULL,
    account_id TEXT NOT NULL,
    login TEXT NOT NULL,
    password TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('main','usd'))
);
CREATE INDEX IF NOT EXISTS accounts_owner_region ON test_accounts(owner_user_id, region);

CREATE TABLE IF NOT EXISTS case_images (
    id SERIAL PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    set_id INTEGER REFERENCES case_sets(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content BYTEA NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS case_images_default ON case_images(set_id) WHERE is_default = 1;
CREATE INDEX IF NOT EXISTS case_images_owner ON case_images(owner_user_id);

CREATE TABLE IF NOT EXISTS test_cases (
    id SERIAL PRIMARY KEY,
    set_id INTEGER NOT NULL REFERENCES case_sets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    request_text TEXT,
    status TEXT NOT NULL DEFAULT 'Not tested'
        CHECK (status IN ('Not tested','Passed','Failed','Blocked','Skipped')),
    qa_comment TEXT NOT NULL DEFAULT '',
    bug_links TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL,
    test_account_id TEXT REFERENCES test_accounts(id) ON DELETE SET NULL,
    client_key TEXT,
    image_id INTEGER REFERENCES case_images(id) ON DELETE RESTRICT,
    UNIQUE (set_id, position)
);
CREATE INDEX IF NOT EXISTS cases_set ON test_cases(set_id);
CREATE UNIQUE INDEX IF NOT EXISTS case_client_key ON test_cases(set_id, client_key);

CREATE TABLE IF NOT EXISTS slack_sends (
    id SERIAL PRIMARY KEY,
    owner_user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id) ON DELETE RESTRICT,
    channel TEXT NOT NULL,
    ts TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    permalink TEXT,
    permalink_error TEXT,
    permalink_checked_at TEXT,
    thread_ts TEXT,
    own_ts TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS slack_sends_owner ON slack_sends(owner_user_id);
CREATE INDEX IF NOT EXISTS sends_thread ON slack_sends(channel, thread_ts);

CREATE TABLE IF NOT EXISTS slack_send_cases (
    send_id INTEGER NOT NULL REFERENCES slack_sends(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    PRIMARY KEY (send_id, case_id)
);
CREATE INDEX IF NOT EXISTS slack_send_cases_case ON slack_send_cases(case_id);

CREATE TABLE IF NOT EXISTS slack_replies (
    id SERIAL PRIMARY KEY,
    send_id INTEGER NOT NULL REFERENCES slack_sends(id) ON DELETE CASCADE,
    event_id TEXT,
    channel TEXT NOT NULL,
    thread_ts TEXT NOT NULL,
    ts TEXT NOT NULL,
    author_id TEXT,
    author_name TEXT,
    text TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    UNIQUE (send_id, ts)
);
CREATE INDEX IF NOT EXISTS replies_send ON slack_replies(send_id);
CREATE INDEX IF NOT EXISTS replies_thread ON slack_replies(channel, thread_ts);

CREATE TABLE IF NOT EXISTS slack_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    received_at TEXT NOT NULL,
    outcome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS slack_stream_events (
    id SERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS stream_events_created ON slack_stream_events(created_at);

CREATE TABLE IF NOT EXISTS slack_oauth_states (
    state TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS oauth_states_expiry ON slack_oauth_states(expires_at);

CREATE TABLE IF NOT EXISTS slack_people (
    slack_user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    team_id TEXT,
    region TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS people_region ON slack_people(region);
CREATE INDEX IF NOT EXISTS people_name ON slack_people(lower(name));

CREATE TABLE IF NOT EXISTS webview_apks (
    licence TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content BYTEA NOT NULL,
    uploaded_at TEXT NOT NULL,
    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS channel_people (
    channel TEXT NOT NULL,
    slack_user_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (channel, slack_user_id)
);
"""

# Owner and scope rules that SQLite expressed as triggers. Postgres spells the
# same intent with a function plus triggers, so the invariants survive the move.
CREATE_RULES = """
CREATE OR REPLACE FUNCTION qahelper_account_scope() RETURNS trigger AS $$
BEGIN
    IF NEW.test_account_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM test_accounts a
        JOIN case_sets s ON s.id = NEW.set_id
        JOIN tasks t ON t.id = s.task_id
        WHERE a.id = NEW.test_account_id
          AND a.owner_user_id = t.owner_user_id
          AND a.region = s.region
    ) THEN
        RAISE EXCEPTION 'Account belongs to a different owner or region';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS case_account_region_insert ON test_cases;
CREATE TRIGGER case_account_region_insert BEFORE INSERT ON test_cases
FOR EACH ROW EXECUTE FUNCTION qahelper_account_scope();

DROP TRIGGER IF EXISTS case_account_region_update ON test_cases;
CREATE TRIGGER case_account_region_update BEFORE UPDATE ON test_cases
FOR EACH ROW EXECUTE FUNCTION qahelper_account_scope();

CREATE OR REPLACE FUNCTION qahelper_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Scope cannot be changed';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS accounts_scope_immutable ON test_accounts;
CREATE TRIGGER accounts_scope_immutable BEFORE UPDATE OF owner_user_id, region ON test_accounts
FOR EACH ROW WHEN (NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
               OR NEW.region IS DISTINCT FROM OLD.region)
EXECUTE FUNCTION qahelper_immutable();

DROP TRIGGER IF EXISTS tasks_owner_immutable ON tasks;
CREATE TRIGGER tasks_owner_immutable BEFORE UPDATE OF owner_user_id ON tasks
FOR EACH ROW WHEN (NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id)
EXECUTE FUNCTION qahelper_immutable();

DROP TRIGGER IF EXISTS slack_sends_owner_immutable ON slack_sends;
CREATE TRIGGER slack_sends_owner_immutable BEFORE UPDATE OF owner_user_id ON slack_sends
FOR EACH ROW WHEN (NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id)
EXECUTE FUNCTION qahelper_immutable();

DROP TRIGGER IF EXISTS case_sets_task_immutable ON case_sets;
CREATE TRIGGER case_sets_task_immutable BEFORE UPDATE OF task_id ON case_sets
FOR EACH ROW WHEN (NEW.task_id IS DISTINCT FROM OLD.task_id)
EXECUTE FUNCTION qahelper_immutable();

DROP TRIGGER IF EXISTS test_cases_set_immutable ON test_cases;
CREATE TRIGGER test_cases_set_immutable BEFORE UPDATE OF set_id ON test_cases
FOR EACH ROW WHEN (NEW.set_id IS DISTINCT FROM OLD.set_id)
EXECUTE FUNCTION qahelper_immutable();

CREATE OR REPLACE FUNCTION qahelper_slack_link_owner() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM slack_sends send
        JOIN test_cases c ON c.id = NEW.case_id
        JOIN case_sets s ON s.id = c.set_id
        JOIN tasks t ON t.id = s.task_id
        WHERE send.id = NEW.send_id AND send.owner_user_id = t.owner_user_id
    ) THEN
        RAISE EXCEPTION 'Slack send and case owners differ';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS slack_link_owner_insert ON slack_send_cases;
CREATE TRIGGER slack_link_owner_insert BEFORE INSERT ON slack_send_cases
FOR EACH ROW EXECUTE FUNCTION qahelper_slack_link_owner();

DROP TRIGGER IF EXISTS slack_link_owner_update ON slack_send_cases;
CREATE TRIGGER slack_link_owner_update BEFORE UPDATE ON slack_send_cases
FOR EACH ROW EXECUTE FUNCTION qahelper_slack_link_owner();
"""

# Ids come from the source database, so every sequence must be moved past them.
RESET_SEQUENCES = """
SELECT setval(pg_get_serial_sequence('users','id'),
              coalesce((SELECT max(id) FROM users), 1));
SELECT setval(pg_get_serial_sequence('tasks','id'),
              coalesce((SELECT max(id) FROM tasks), 1));
SELECT setval(pg_get_serial_sequence('case_sets','id'),
              coalesce((SELECT max(id) FROM case_sets), 1));
SELECT setval(pg_get_serial_sequence('test_cases','id'),
              coalesce((SELECT max(id) FROM test_cases), 1));
SELECT setval(pg_get_serial_sequence('slack_sends','id'),
              coalesce((SELECT max(id) FROM slack_sends), 1));
SELECT setval(pg_get_serial_sequence('slack_replies','id'),
              coalesce((SELECT max(id) FROM slack_replies), 1));
SELECT setval(pg_get_serial_sequence('slack_stream_events','id'),
              coalesce((SELECT max(id) FROM slack_stream_events), 1));
SELECT setval(pg_get_serial_sequence('case_images','id'),
              coalesce((SELECT max(id) FROM case_images), 1));
"""

# Insert order follows the foreign keys; the columns are listed explicitly so a
# column added later cannot silently shift the values.
IMPORT_ORDER = (
    ("users", "id,auth_provider,auth_subject,display_name,created_at,updated_at,"
              "slack_token,slack_user_id,slack_team_id,slack_scopes,slack_token_issued_at"),
    ("tasks", "id,owner_user_id,jira_id,title,created_at,updated_at,settings,region,"
              "client_key,status"),
    ("case_sets", "id,task_id,name,created_at,settings,region,operation,mention_users,"
                  "generation_key"),
    ("test_accounts", "id,owner_user_id,region,name,account_id,login,password,kind"),
    ("case_images", "id,owner_user_id,set_id,filename,media_type,size_bytes,content,"
                    "is_default,created_at,updated_at"),
    ("test_cases", "id,set_id,position,title,text,comment,request_text,status,"
                   "qa_comment,bug_links,updated_at,test_account_id,client_key,image_id"),
    ("slack_sends", "id,owner_user_id,channel,ts,sent_at,permalink,permalink_error,"
                    "permalink_checked_at,thread_ts,own_ts"),
    ("slack_send_cases", "send_id,case_id"),
    ("slack_replies", "id,send_id,event_id,channel,thread_ts,ts,author_id,author_name,"
                      "text,received_at"),
    ("slack_events", "event_id,event_type,received_at,outcome"),
    ("slack_stream_events", "id,event_id,payload,created_at"),
    ("slack_oauth_states", "state,user_id,created_at,expires_at"),
    ("slack_people", "slack_user_id,name,team_id,region,fetched_at,updated_at"),
    ("webview_apks", "licence,filename,size_bytes,content,uploaded_at,uploaded_by"),
    ("channel_people", "channel,slack_user_id,name,created_at"),
)


def import_sqlite(db, db_path: Path) -> dict:
    """Copy a local SQLite database into an empty PostgreSQL schema.

    Tables that do not exist in the source are skipped, so a database from an
    older build still imports. Every table is copied in one statement per
    table; ids, timestamps and blobs are preserved as they are.
    """
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    copied = {}
    try:
        existing = {row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table, columns in IMPORT_ORDER:
            if table not in existing:
                continue
            rows = source.execute(f"SELECT {columns} FROM {table}").fetchall()
            if not rows:
                copied[table] = 0
                continue
            placeholders = ",".join("%s" for _ in columns.split(","))
            db.executemany(
                f"INSERT INTO {table}({columns}) VALUES({placeholders})",
                [tuple(row) for row in rows],
            )
            copied[table] = len(rows)
        db.execute(RESET_SEQUENCES)
        db.commit()
    finally:
        source.close()
    return copied
