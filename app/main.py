import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.slack_client import post_message
from app.slack_oauth import build_authorize_url, exchange_code

load_dotenv()

app = FastAPI(title="QA Testcase Slack Integration")

# MVP only. Replace with persistent per-user storage before multi-user use.
OAUTH_STATES: set[str] = set()
USER_TOKEN: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    connected = USER_TOKEN is not None
    return f"""
    <html>
      <body style="font-family: sans-serif; max-width: 760px; margin: 40px auto;">
        <h1>QA Testcase Slack Integration</h1>
        <p>Slack connected: <strong>{connected}</strong></p>
        <p><a href="/slack/oauth/start">Connect Slack</a></p>
        <form method="post" action="/slack/send">
          <textarea name="text" rows="10" style="width:100%;">Hello from QA testcase integration</textarea><br><br>
          <button type="submit">Send to Slack</button>
        </form>
      </body>
    </html>
    """


@app.get("/slack/oauth/start")
async def slack_oauth_start() -> RedirectResponse:
    try:
        url, state = build_authorize_url()
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing env var: {exc.args[0]}") from exc
    OAUTH_STATES.add(state)
    return RedirectResponse(url)


@app.get("/slack/oauth/callback", response_class=HTMLResponse)
async def slack_oauth_callback(code: str, state: str) -> str:
    global USER_TOKEN

    if state not in OAUTH_STATES:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    OAUTH_STATES.discard(state)

    data = await exchange_code(code)
    authed_user = data.get("authed_user") or {}
    token = authed_user.get("access_token")
    if not token:
        raise HTTPException(status_code=500, detail="Slack did not return a user access token")

    USER_TOKEN = token
    return '<p>Slack connected. <a href="/">Back</a></p>'


@app.post("/slack/send", response_class=HTMLResponse)
async def slack_send(text: str = Form(...)) -> str:
    if not USER_TOKEN:
        raise HTTPException(status_code=401, detail="Connect Slack first")

    channel_id = os.getenv("SLACK_CHANNEL_ID")
    if not channel_id:
        raise HTTPException(status_code=500, detail="Missing SLACK_CHANNEL_ID")

    result = await post_message(USER_TOKEN, channel_id, text)
    ts = result.get("ts", "unknown")
    return f'<p>Sent to Slack. ts={ts}</p><p><a href="/">Back</a></p>'
