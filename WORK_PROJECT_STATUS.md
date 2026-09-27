# Work Project Status

## Current milestone

Slack OAuth MVP was verified in the personal test workspace `KorolevForTest`. The generator and region-based Slack delivery are implemented. Latest generator, editing and per-case instructions changes were pushed to `main` in commit [`f3f58d4ffb97b11395d2187d2b4c6fcff389fa44`](https://github.com/KaramazovBrothers/qa-testcase-slack-integration/commit/f3f58d4ffb97b11395d2187d2b4c6fcff389fa44). User review and live verification of these latest changes are pending.

Verified on 2026-09-27:

- A separate Slack app `DKTestSender` was created for development/testing.
- The app uses a user OAuth scope: `chat:write`.
- A local FastAPI backend is running on port `8000`.
- A public HTTPS callback is exposed through ngrok.
- Slack OAuth completes successfully.
- The backend receives a Slack user access token.
- A message was sent to Slack channel `#new-channel`.
- The message appeared from the authorized Slack user, not from a bot.
- Real secrets remain only in the local `.env` file and are excluded from Git.

Successful end-to-end flow:

```text
Local UI
  -> /slack/oauth/start
  -> Slack OAuth
  -> public ngrok callback
  -> FastAPI /slack/oauth/callback
  -> user access token
  -> POST /slack/send
  -> Slack chat.postMessage
  -> #new-channel
  -> message from the authorized user
```

## Current project structure

```text
qa-testcase-slack-integration/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── slack_client.py
│   ├── slack_oauth.py
│   ├── slack_routes.py
│   └── static/
│       └── generator.html
├── config/
│   └── slack_routes.example.json
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Important current limitations

This is still an MVP.

- The Slack user token is stored only in application memory.
- Restarting the backend removes the current OAuth session/token.
- Only one authorized user is supported.
- Generated cases use region-based routing; `SLACK_CHANNEL_ID` is a fallback.
- A standalone local HTML file supports generation/editing/copying, but Slack sending requires the backend and an authorized session.
- Confluence is not integrated yet.
- ngrok is only for local development and will not be used in production.

## Security rules

Never commit:

- `.env`
- `SLACK_CLIENT_SECRET`
- Slack user access tokens
- production credentials

The repository keeps only `.env.example` with empty values.

For production, application secrets will be stored in the deployment/server secret storage. Dynamic Slack user tokens will later require protected persistent storage.

## Existing generator

`KaramazovBrothers/generator-tests-for-agregator` is a separate existing project.

Rules for this integration project:

- use the old project only as a source/reference for test-case generation logic;
- do not push Slack integration changes into the old repository;
- all new development belongs in `qa-testcase-slack-integration`;
- the generator will likely be significantly redesigned later.

## Next milestone

Verify the latest changes with the user:

1. Pull `main`, restart FastAPI and reconnect Slack if the token was lost.
2. Open `http://localhost:8000/generator`.
3. Check the agreed scenarios, edit a case and add multiline additional instructions.
4. Test single-case and send-all actions: each case must have its own parent message/thread; edited title/body appear first, followed by a separate additional-information reply only when filled.
5. Check blank comments, region routing, mentions, formatting and Slack message-size constraints.
6. Confluence integration and persistent multi-user OAuth/token storage remain future work.

## Production direction

Development:

```text
Slack -> ngrok HTTPS -> localhost:8000 -> FastAPI
```

Production will instead use a company-hosted HTTPS endpoint:

```text
Slack -> company HTTPS callback / ingress -> backend service
```

The source code may live in the company GitLab repository, while the running backend will be deployed to company infrastructure. The production Slack app should be a separate company-controlled app, not the personal development app.


## Update: generator connected to Slack

Implemented after the OAuth MVP:

- Added `app/static/generator.html` based on the existing generator as a temporary training/reference copy.
- Added a new `Send to Slack` action next to the existing generator actions.
- Added `GET /generator` to serve the generator from the FastAPI backend.
- Added `POST /slack/send-cases`.
- Generated cases are sent through the authorized Slack user token; the current thread structure is described below.
- The original repository `generator-tests-for-agregator` was not modified.

Next verification step:

1. Pull the latest changes locally.
2. Restart the FastAPI backend.
3. Reconnect Slack because the current token is in memory.
4. Open `http://localhost:8000/generator`.
5. Generate test cases.
6. Press `Send to Slack`.
7. Verify that all generated cases arrive in the configured Slack channel from the authorized user.


## Update: region routing, mentions and Slack threads

Implemented:

- Removed the accidental visible `\\n` between generator buttons.
- The selected generator region is now sent to the backend.
- Added region-based Slack routing through `config/slack_routes.json`.
- Added `config/slack_routes.example.json` as a template.
- Local `config/slack_routes.json` is ignored by Git.
- Added optional fallback `SLACK_MENTION_USER_IDS` in `.env`.
- Slack user mentions use Slack user IDs in the form `<@U...>`.
- Each generated case creates its own parent channel message:
  `@users Привет! Просьба провести тест депозита`
- That case's title and body are posted as a reply using the parent `thread_ts`.
- If the case has additional instructions, a second reply is posted below the case description in the same thread.
- Send-all creates separate parent messages/threads for the cases, not one shared thread.

Current routing priority:

1. Region entry in `config/slack_routes.json`.
2. `default` entry in that file.
3. Fallback to `SLACK_CHANNEL_ID` and `SLACK_MENTION_USER_IDS` from `.env`.

The route config stores Slack channel IDs and Slack user IDs, not secrets.

## Update 2026-09-27: agreed generator behavior and review history

Scope and repository separation:

- Only `qa-testcase-slack-integration` is in scope for the latest changes.
- An aggregator preview was prepared earlier, but the user explicitly excluded it from this change set. Do not transfer or push these changes to `generator-tests-for-agregator`.
- The user's requirement for the separate aggregator's minimal suite remains two cases. This Slack generator has only the full suite.
- Structural analysis used source reads. The codebase-memory skill was inaccessible and graph tools were unavailable; no two-repository graph analysis was performed.

Platforms and amount changes:

- Zazino uses PWA, with no native or WebView cases.
- With amount change enabled, Zazino has overpayment on PWA and underpayment on Android Chrome.
- PINCO/WL and COM retain native and WebView support. COM's separate USD-user scenario remains.
- License default sites and an explicit Site URL override are preserved.

QR and mobile transitions:

- Titles identify the actual QR route: phone camera, payment-app camera, downloaded QR, or payment-app button. Receipt variants remain visible.
- The user ultimately chose to keep BOTH saved-payment-data scenarios: after timer expiry and after cancellation. The earlier suggestion to reduce them to one was superseded.
- Payment-app button transitions apply only to mobile browsers/apps, never Desktop. Desktop QR scanning remains.
- Where button transitions are enabled, timer/cancellation cases first open the payment app without paying, return to the original form, and then continue their scenario.
- QR download mode uses a separate button precheck when OneClick is enabled.
- Existing receipt, dispute/callback, cancellation and browser-coverage checks remain.

HPP return to cashier:

- Added the checkbox “Кнопка возврата в кассу присутствует на главном экране провайдера”.
- It is hidden/disabled for H2H and has no effect there.
- When enabled for HPP, after opening the provider page the case clicks “Вернуться в кассу”, verifies that the cashier is open on the original platform, pending popup is displayed and the user remains authorized.
- The next step uses the user's final wording: “Повторить необходимые действия для возврата на страницу провайдера.”
- Earlier explicit instructions to choose the method and enter the amount again were removed.
- Cashier-return steps also check “Касса открыта, пользователю отображается pending popup”, following the user's requested expectation.
- “проверка кнопки возврата в кассу” was removed from case titles; the checkbox-controlled steps remain.

Editing and additional instructions:

- Every case has “Редактировать” / “Готово” to edit its title and entire generated body.
- Each case has an optional additional-instructions field.
- Single-case sending, send-all and copying read the current edited content.
- Backend `GeneratedCase.comment` defaults to an empty string for compatibility.
- A nonblank comment is sent after the case description in the same thread as:
  `Дополнительная информация:\n<user text>`.
- Empty/whitespace-only comments do not produce a reply. Copying includes nonblank instructions too.
- Both `app/static/generator.html` and `app/main.py` must be updated together.

Validation and delivery:

- Earlier generation checks covered 87,552 configurations; the Slack full-suite output was compared with the corresponding preview at that stage.
- Later targeted checks covered cashier-return steps, pending popup expectations, sequential numbering and removal of repeated amount entry.
- JavaScript/Python syntax checks passed before the push.
- Mocked backend checks verified edited text, comment order, matching thread IDs and omission of blank comments. Serialization/copy checks also passed.
- These are local/automated checks, not proof of a live Slack send for the latest version. No live Slack messages were sent during this change.
- The user authorized pushing and required a separate new commit. Commit `f3f58d4ffb97b11395d2187d2b4c6fcff389fa44` was pushed to `main`; the aggregator repository was not changed.
- Next action: user reviews the backend-served generator and verifies actual Slack delivery.
