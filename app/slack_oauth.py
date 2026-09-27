import os
import secrets
from urllib.parse import urlencode

import httpx

SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"


def build_authorize_url() -> tuple[str, str]:
    client_id = os.environ["SLACK_CLIENT_ID"]
    redirect_uri = os.environ["SLACK_REDIRECT_URI"]
    state = secrets.token_urlsafe(32)
    query = urlencode({
        "client_id": client_id,
        "user_scope": "chat:write",
        "redirect_uri": redirect_uri,
        "state": state,
    })
    return f"{SLACK_AUTHORIZE_URL}?{query}", state


async def exchange_code(code: str) -> dict:
    payload = {
        "client_id": os.environ["SLACK_CLIENT_ID"],
        "client_secret": os.environ["SLACK_CLIENT_SECRET"],
        "code": code,
        "redirect_uri": os.environ["SLACK_REDIRECT_URI"],
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(SLACK_TOKEN_URL, data=payload)
        response.raise_for_status()
        data = response.json()

    if not data.get("ok"):
        raise RuntimeError(f"Slack OAuth failed: {data.get('error', 'unknown_error')}")
    return data
