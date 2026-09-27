# Work Project Status

## Current milestone

Slack OAuth MVP is working successfully in the personal test workspace `KorolevForTest`.

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
│   └── slack_oauth.py
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
- The Slack channel is configured through `SLACK_CHANNEL_ID`.
- The test-case generator is not integrated yet.
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

Integrate generated test cases into the working Slack flow:

1. Extract/adapt the output-generation logic from `generator-tests-for-agregator`.
2. Generate the same test-case text inside this project.
3. Send the generated text through the already working `/slack/send` flow.
4. Verify formatting and Slack message-size constraints.
5. Then connect the UI to Confluence.
6. After that, replace the single in-memory token with a multi-user OAuth/token storage model.

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
- Generated cases are sent to Slack one case per message using the already authorized Slack user token.
- The original repository `generator-tests-for-agregator` was not modified.

Next verification step:

1. Pull the latest changes locally.
2. Restart the FastAPI backend.
3. Reconnect Slack because the current token is in memory.
4. Open `http://localhost:8000/generator`.
5. Generate test cases.
6. Press `Send to Slack`.
7. Verify that all generated cases arrive in the configured Slack channel from the authorized user.
