# QA Testcase Slack Integration

Initial scaffold for Slack OAuth and test-case delivery from Confluence.

## Local QA workspace (Python 3.11)

```sh
cd /Users/d.karaliou/Documents/qa-testcase-slack-integration
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open **http://127.0.0.1:8000/app**. The existing standalone generator remains at
`/generator`. No frontend build, Node.js, React or external database is needed.
If port 8000 is already occupied by the old backend, stop that process first.

1. Create a task with its Jira ID and title, or search/select an existing task.
2. Expand the generator, enter its parameters and save settings for the task.
3. Generate and edit cases using the existing generator. Click **Сохранить новый
   набор** below it. This saves a new independent set and the task settings; older
   sets are kept. Generation by itself is a preview and does not write a set.
4. Choose a saved set from history. Status, QA comments, bug URLs and case edits
   save when leaving a field; the save button also saves immediately. Errors stay
   visible and unsaved edits are retained. Counts show all cases in the selected
   set, including those hidden by a status filter.
5. **Взять настройки набора** copies that set's settings into the generator;
   save them explicitly or create a new set. Switching tasks clears the preview
   and restores the selected task's own settings.
6. Connect the corporate Slack App using **Подключить Slack**. The current saved
   set is sent using its saved region, operation and mentions and its current
   edited text. QA comments/bug links remain local; additional Slack instructions
   retain their existing meaning. Sending is an explicit button action.

### Data and access

- SQLite is initialized at startup in `data/qa_tests.db`, relative to the project,
  independently of the shell's current directory. Its permissions are `0600`.
- Settings include every generator field, including local test-account passwords,
  language, payout-fee mode and regional mention edits. Each set keeps a settings
  snapshot; cases keep their own status, QA comment and bug-link list.
- Data is local and not encrypted by the application. Stop the backend before
  backing up/restoring `data/qa_tests.db`. Keep backups outside Git.
- Deleting a task deletes its settings, sets and cases; the UI asks for confirmation.
- `.env`, local routing, databases/journals and `data/` are ignored by Git.
- `/app`, its assets, `/api/tasks`, `/generator`, Slack sending and connection
  status accept only direct loopback requests with a loopback Host. Forwarding
  headers and cross-site/origin requests are rejected. Keep `--no-proxy-headers`
  and `--host 127.0.0.1`. There is no remote management/login mode.
- ngrok may expose the OAuth callback, but must not be used to open the workspace.
  The callback remains public so existing User OAuth works. User token and OAuth
  state remain in memory; restart requires reconnecting Slack.
- No changes were made to OAuth scopes, the existing post-message transport, channel routing or
  message/thread construction. Never substitute a Bot Token.

### Local API

Interactive schema: `http://127.0.0.1:8000/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `/api/tasks` | List (optional `?q=QA-123`) / create |
| GET / PUT / DELETE | `/api/tasks/{task_id}` | Read / replace task metadata / delete |
| GET / PUT | `/api/tasks/{task_id}/settings` | Read / replace generator settings |
| GET / POST | `/api/tasks/{task_id}/sets` | List / create a new immutable-membership set |
| GET | `/api/tasks/{task_id}/sets/{set_id}` | Read cases, snapshot and status counts |
| PATCH | `/api/tasks/{task_id}/sets/{set_id}/cases/{case_id}` | Update any subset of case fields |
| GET | `/api/slack-status` | Connection flag without exposing the token |

Case updates support `status` (`Not tested`, `Passed`, `Failed`, `Blocked`,
`Skipped`), `qa_comment`, `bug_links` (HTTP(S) URLs), `title`, `text`, `comment`
(existing Slack instructions), and `request_text`. Creation returns 201, deletion
204, missing/cross-task records 404, duplicate Jira IDs 409 and invalid inputs 422.
Writes are transactional and foreign keys enforce cascading deletion.

### Tests

```sh
cd /Users/d.karaliou/Documents/qa-testcase-slack-integration
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary databases and mocked Slack calls. They do not send messages,
read production tokens or alter the real QA database. Browser verification of the
2026-10-26 update also compared 162 configurations / 868 cases with the original
generator and checked task switching, settings, history, statuses and reloads.


### Slack message links and delivery history

Send saved cases from `/app` using the per-case button or the current-set button.
Each saved case displays **Открыть в Slack** and the history of its sends, including
UTC send time, channel and exact string timestamp. The link points to the reply
containing the case body; parent requests and additional instructions retain
exactly the existing format and thread structure.

After Slack acknowledges the body message, its response `channel` and `ts` are
committed to SQLite before calling `chat.getPermalink`. If lookup fails, the send
remains recorded without a link. **Получить ссылку** retries only the lookup and
never invokes `chat.postMessage`. A failure in a later instructions reply or case
does not remove already recorded sends. The UI reloads history after partial
errors and never automatically resends a batch.

- `slack_sends` stores each delivery; `slack_send_cases` associates it with one or
  more cases. New manual sends append history. Deleting cases removes their links;
  a shared delivery remains while at least one associated case exists.
- `POST /slack/send-cases` accepts optional `case_ids: [1, 2]` on each message item.
  All IDs are validated before posting. One combined item creates one body message
  and one delivery associated with every supplied ID; no grouping or formatting
  changes are introduced by this feature. The current generator sends separate
  threads and the workspace supplies one ID per case.
- `GET /api/tasks/{task_id}/sets/{set_id}` includes `slack_sends` per case.
- `POST /api/tasks/{task_id}/sets/{set_id}/cases/{case_id}/slack-sends/{send_id}/permalink`
  resolves a pending link. It validates task/set/case ownership, requires the
  existing User OAuth session, and is protected by the local-access middleware.
  A lookup failure returns the recorded send with a null permalink and error;
  it is not a failed or unperformed message send.
- Unpersisted generator previews have no database case IDs. Save them as a set and
  send from the saved-case section to keep delivery history. Legacy requests
  without IDs keep their previous sending behavior.
- No additional permissions: `chat.getPermalink` requires no extra scopes;
  User OAuth remains `user_scope=chat:write`.
  Reference: https://docs.slack.dev/reference/methods/chat.getPermalink/

Verification: all 19 unittest tests pass. New checks cover additive database
initialization, exact response metadata, message-format regression, repeated and
shared sends, lookup errors/retries without posting, partial delivery, restart,
access checks, HTTP 429 and permalink validation. Browser checks used mocked
Slack exclusively and verified links, pending retries, history, reload and send-all.


### Database ownership: ready for multiple users

The schema has versioned ownership support (`PRAGMA user_version = 1`):

- `users`: internal ID, unique `(auth_provider, auth_subject)`, display name and
  creation/update times. A provider subject is a stable identity; email/display
  name is not used as the ownership key.
- `tasks.owner_user_id`: required FK to `users`. Jira IDs are unique per owner,
  case-insensitively, so two users can save independent copies of the same ticket.
- Settings belong to their task. Sets, cases, statuses, QA comments and bug links
  inherit ownership through `task -> case_set -> test_case`; no duplicated owner
  columns can become inconsistent in these child tables.
- `slack_sends.owner_user_id`: FK to users. Database triggers reject links from
  one user's send to another user's cases. Existing shared-message behavior is
  supported among the same owner's cases. Ownership transfer is deliberately
  unsupported; tree parent/owner IDs cannot be updated in place.
- Every task/settings/set/case API path checks ownership; list/search is scoped
  to the current user. Other users' IDs return 404. Slack case IDs are validated
  against the owner before any message is posted.

On upgrade, the application first creates a SQLite backup in
`data/backups/qa_tests.pre-users.<UTC timestamp>.db` (permissions 0600), then
transactionally migrates existing tasks and Slack history to **Local QA** (ID 1).
Existing IDs, settings, case results and links are preserved. Foreign-key checks
run before commit, errors roll back, and repeat startup does not duplicate users
or backups. Backups remain under the Git-ignored data directory. Stop the backend
before restoring a backup; deploy the matching application version as needed.

This is database/API preparation, **not a multi-user login release**. The
server-owned `get_current_user_id` dependency currently returns the local user.
Clients cannot choose another owner using a header, query parameter or request
body. A future authentication implementation must replace this dependency with
validated session/identity-provider data and create/resolve the corresponding
user. There is no user switcher, registration, user deletion or shared-task ACL.

User OAuth scope and message format remain unchanged. The current in-memory Slack
session belongs only to Local QA; other identities cannot reuse its token. Before
real multi-user operation, OAuth state/token storage must also be scoped to each
user and authentication/access protection must be implemented. The local-only
access restriction remains in place. The standalone generator still works
without creating a task.

All 27 automated tests pass, including two-user API isolation, duplicate Jira IDs
across owners, rejected cross-owner Slack links, migration backup/data retention,
rollback and newer-schema protection. All Slack tests use mocks.
