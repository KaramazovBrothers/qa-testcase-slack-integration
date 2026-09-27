import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.slack_client import post_message
from app.slack_oauth import build_authorize_url, exchange_code

load_dotenv()

app = FastAPI(title="QA Testcase Slack Integration")

BASE_DIR = Path(__file__).resolve().parent

# MVP only. Replace with persistent per-user storage before multi-user use.
OAUTH_STATES: set[str] = set()
USER_TOKEN: Optional[str] = None


class GeneratedCase(BaseModel):
    title: str
    text: str


class SendCasesRequest(BaseModel):
    cases: list[GeneratedCase]


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    connected = USER_TOKEN is not None
    return f"""
    <html>
      <body style="font-family: sans-serif; max-width: 760px; margin: 40px auto;">
        <h1>QA Testcase Slack Integration</h1>
        <p>Slack connected: <strong>{connected}</strong></p>
        <p><a href="/slack/oauth/start">Connect Slack</a></p>
        <p><a href="/generator">Open testcase generator</a></p>
        <form method="post" action="/slack/send">
          <textarea name="text" rows="10" style="width:100%;">Hello from QA testcase integration</textarea><br><br>
          <button type="submit">Send to Slack</button>
        </form>
      </body>
    </html>
    """


@app.get("/generator")
async def generator() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "generator.html", media_type="text/html")


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


def require_slack_context() -> tuple[str, str]:
    if not USER_TOKEN:
        raise HTTPException(status_code=401, detail="Connect Slack first")

    channel_id = os.getenv("SLACK_CHANNEL_ID")
    if not channel_id:
        raise HTTPException(status_code=500, detail="Missing SLACK_CHANNEL_ID")

    return USER_TOKEN, channel_id


@app.post("/slack/send", response_class=HTMLResponse)
async def slack_send(text: str = Form(...)) -> str:
    user_token, channel_id = require_slack_context()
    result = await post_message(user_token, channel_id, text)
    ts = result.get("ts", "unknown")
    return f'<p>Sent to Slack. ts={ts}</p><p><a href="/">Back</a></p>'


@app.post("/slack/send-cases")
async def slack_send_cases(payload: SendCasesRequest) -> dict:
    user_token, channel_id = require_slack_context()

    if not payload.cases:
        raise HTTPException(status_code=400, detail="No generated cases")

    sent = 0
    for case in payload.cases:
        message = f"{case.title}\n\n{case.text}"
        await post_message(user_token, channel_id, message)
        sent += 1

    return {"ok": True, "sent": sent}
