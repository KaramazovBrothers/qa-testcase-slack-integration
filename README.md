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

1. Start a draft or select a saved task. Jira ID and title are optional. If either
   is missing, Save assigns “Без названия N” with no Jira ID.
2. Fill the existing generator and generate cases. **Сохранить** is the single
   save action for task metadata, settings, test accounts and the current cases.
   Saving before generation stores settings only. Repeated saves update the same
   cases; regeneration replaces the contents of the same set when saved.
3. Add/remove test accounts (account ID, login, password) in **Пользователи выбранного региона**.
   The dropdown on each case selects an account and replaces its credential
   headers, preserving the scenario. These accounts are distinct from application
   users and Slack mentions. Removing an account clears its assignments but keeps
   existing case text as a snapshot.
4. **Редактировать кейс и текст для Slack** at the top of each card enables inline
   editing. Statuses, comments, edits and case deletions are applied by
   **Сохранить**. Switching away from unsaved work requires confirmation.
5. Each task has one editable set; there is no generation-history selector.
   A saved task has one fixed region; only that region's mention list is stored.
   Start another draft for a different region.
6. Connect the corporate Slack App with **Подключить Slack**, then explicitly
   send a case or set. Sending first saves current changes and retains permalink
   history. QA comments/bug links remain local; Slack request/additional text
   retains its existing meaning. Failed permalink lookup never reposts messages.

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
| GET / POST | `/api/tasks/{task_id}/sets` | List / create a new set |
| GET | `/api/tasks/{task_id}/sets/{set_id}` | Read cases, snapshot and status counts |
| PATCH / DELETE | `/api/tasks/{task_id}/sets/{set_id}/cases/{case_id}` | Update case fields / delete case |
| POST | `/api/tasks/save` | Atomically save task, settings, accounts and current set |
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

The schema has versioned ownership support (`PRAGMA user_version = 4`):

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

### Regional test accounts (schema version 3)

The generator separates **Метод и суммы** from **Пользователь**. Main and USD
user fields have a saved-user dropdown for the selected region. Selecting an
account fills ID/login/password; changing credentials switches to manual entry.
The common **Сохранить** saves new manually entered credentials even without
cases. Identical credentials in the same region are reused, not duplicated.
The standalone `/generator` offers **Сохранить пользователей региона** without
creating a task. On region change, credential fields are cleared and the new
region's catalog is loaded.

`test_accounts.owner_user_id` references `users.id`; `test_accounts.region` scopes
the catalog. Accounts can be reused across the owner's tasks in that region.
`test_cases.test_account_id` references the account; database triggers forbid
cross-owner and cross-region assignments. Deleting a task keeps the catalog.
Deleting an account explicitly clears its assignments across tasks, preserving
existing case text. Omitting accounts from Save never deletes the catalog.
These test accounts are distinct from application login identities and Slack
mentions. Credentials remain local in the ignored SQLite file.

GET `/api/tasks/accounts?region=EC` lists the owner's regional catalog.
POST `/api/tasks/accounts` accepts `region`, `test_accounts` and optional
`deleted_account_ids` without creating tasks. The unified Save accepts explicit
`deleted_account_ids` too. Manual duplicate entries resolve to existing IDs.

Schema upgrades are transactional with private backups under `data/backups`.
Version 3 creates `qa_tests.pre-region-accounts.*.db` before changing the schema.
The user's requested reset clears the active local database once during this
update; application startup does not clear data. Previous local backups remain.

Verification: 35 Python tests plus browser coverage of split blocks, saving
without cases, region filtering, reuse across tasks, manual entries, duplicates,
reload and standalone saving. Generator output matches the previous version for
162 configurations / 868 cases. Slack calls remain mocked in automated tests.

### Single editable set and UI corrections (schema version 4)

Each task has at most one case set, enforced by a unique database index. Both
save APIs reuse it; editing preserves case IDs and their Slack history, while
explicit regeneration replaces the case list on Save. During upgrade the latest
existing set is retained, with older sets backed up in the private
`data/backups/qa_tests.pre-single-set.*.db` before removal.

Save aligns with the metadata inputs. Selecting a region before generating cases
no longer opens a confirmation dialog. Test-account password fields are visible.
The Jira bug-link editor is removed, and empty Slack-history containers are
hidden; actual sent-message links and permalink retry remain available.
Ordinary payouts are titled “выплата” and omit Commission: 0% and the commission
precondition. Fee payouts show “Уведомление: Выплата будет с комиссией 25%”.

Verified: 36 Python tests, browser checks for the listed fixes, stable case IDs
on editing, reload and single-set regeneration. Deposit generation remains
identical to the previous version across 108 configurations / 742 cases.
