import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Optional

if sys.version_info < (3, 10):  # noqa: UP036 - must run before the annotations below
    raise RuntimeError(
        "Python 3.10 or newer is required (found "
        f"{sys.version_info.major}.{sys.version_info.minor}). "
        "The code uses 'X | None' annotations, which older versions reject at import time."
    )

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from typing import Literal
from app.mentions import normalize_mentions, format_mentions

from app.slack_client import post_message, upload_file
from app import webview_apk
from app.slack_oauth import build_authorize_url, exchange_code
from app.slack_routes import get_slack_route

load_dotenv()

from app import slack_events, storage, slack_history, slack_oauth_state_migration, slack_people
from app.current_user import CurrentUserId
from app.local_api import router as local_router
from app.workspace_api import router as workspace_router
from app.webview_api import router as webview_router
from app.local_access import LocalAccessMiddleware


@asynccontextmanager
async def lifespan(app):
    storage.initialize()
    yield


app = FastAPI(title="QA Testcase Slack Integration", lifespan=lifespan)
app.add_middleware(LocalAccessMiddleware)
app.include_router(workspace_router)
app.include_router(local_router)
app.include_router(webview_router)


@app.get("/app", include_in_schema=False)
async def workspace():
    return FileResponse(BASE_DIR / "static" / "workspace.html", media_type="text/html")


# Built assets: `scripts/build_static.py` writes these from static-src/.
ASSETS = {
    "workspace.js": "application/javascript",
    "workspace.css": "text/css",
    "generator.js": "application/javascript",
    "generator.css": "text/css",
}


@app.get("/app/{asset}", include_in_schema=False)
async def workspace_asset(asset: str):
    media_type = ASSETS.get(asset)
    if media_type is None:
        raise HTTPException(404, "Not found")
    return FileResponse(BASE_DIR / "static" / asset, media_type=media_type)


@app.get("/api/slack-status")
async def slack_status(user_id: CurrentUserId = storage.LOCAL_USER_ID):
    """Whether the current user personally connected Slack."""
    return {"connected": storage.get_slack_token(user_id) is not None}


@app.get("/api/slack-diagnostics")
async def slack_diagnostics(user_id: CurrentUserId = storage.LOCAL_USER_ID):
    """Report the identity and scopes Slack actually granted this user."""
    token = require_slack_token(user_id)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = response.json()
    stored = storage.get_slack_identity(user_id)
    return {
        "ok": data.get("ok"),
        "team": data.get("team"),
        "team_id": data.get("team_id"),
        "user": data.get("user"),
        "user_id": data.get("user_id"),
        "stored_slack_user_id": stored.get("slack_user_id"),
        "stored_scopes": stored.get("scopes"),
        "issued_at": stored.get("issued_at"),
        "granted_scopes": [s for s in (response.headers.get("x-oauth-scopes") or "").split(",") if s],
        "error": data.get("error"),
    }


BASE_DIR = Path(__file__).resolve().parent


class GeneratedCase(BaseModel):
    case_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(default_factory=list, max_length=500)
    title: str
    text: str
    comment: str = ""
    request_text: Optional[str] = Field(default=None, max_length=2000)
    # Set for WebView cases: the build of this licence rides along in the thread.
    licence: Optional[Literal["com", "pinco", "zazino"]] = None


class SendCasesRequest(BaseModel):
    region: str
    cases: list[GeneratedCase]
    mention_users: Optional[list[str]] = Field(default=None, max_length=100)
    operation: Literal["deposit", "payout"] = "deposit"
    request_text: Optional[str] = Field(default=None, max_length=2000)


class ResolvePeopleRequest(BaseModel):
    entries: list[str] = Field(default_factory=list, max_length=100)
    refresh: bool = False


class AddPersonRequest(BaseModel):
    entry: str = Field(min_length=1, max_length=300)
    region: str = Field(min_length=1, max_length=8)
    name: Optional[str] = Field(default=None, max_length=200)


class ForgetPersonRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=80)


@app.get("/api/slack/people")
async def slack_people_directory(region: str = "", user_id: CurrentUserId = storage.LOCAL_USER_ID) -> dict:
    """The shared people directory, optionally limited to one region."""
    if region:
        people = slack_people.in_region(region)
        return {"people": people, "names": {p["id"]: p["name"] or p["id"] for p in people}}
    return {"names": slack_people.all_cached()}


@app.post("/api/slack/people")
async def slack_people_lookup(
    payload: ResolvePeopleRequest, user_id: CurrentUserId = storage.LOCAL_USER_ID
) -> dict:
    """Turn pasted profile links/IDs into member IDs plus readable names.

    Accepts exactly what a person copies out of Slack, so nobody has to know
    that a member ID exists. A missing token or a Slack error leaves the ID
    stored and simply omits the name.
    """
    try:
        member_ids = normalize_mentions(payload.entries)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token = storage.get_slack_token(user_id)
    people = []
    for member_id in member_ids:
        name = await slack_people.resolve(token, member_id, refresh=payload.refresh)
        people.append({"id": member_id, "name": name or "", "label": name or member_id})
    return {"people": people, "names": {p["id"]: p["label"] for p in people}}


@app.post("/api/slack/people/directory")
async def slack_people_add(
    payload: AddPersonRequest, user_id: CurrentUserId = storage.LOCAL_USER_ID
) -> dict:
    """Save one person to the shared directory under a region.

    The name comes from Slack when `users:read` is granted, otherwise from the
    caller. An entry that cannot be resolved is still saved by ID: the mention
    works, only the label is missing.
    """
    try:
        member_ids = normalize_mentions([payload.entry])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not member_ids:
        raise HTTPException(status_code=400, detail="No person to add")

    member_id = member_ids[0]
    name = (payload.name or "").strip()
    if not name:
        token = storage.get_slack_token(user_id)
        name = (await slack_people.resolve(token, member_id) or "").strip()
    slack_people.remember(member_id, name, region=payload.region, from_slack=not payload.name)
    return {"ok": True, "id": member_id, "name": name, "region": payload.region}


@app.delete("/api/slack/people/directory")
async def slack_people_forget(
    payload: ForgetPersonRequest, user_id: CurrentUserId = storage.LOCAL_USER_ID
) -> dict:
    """Remove one person from the shared directory."""
    removed = slack_people.forget(payload.member_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Person not found in the directory")
    return {"ok": True, "removed": payload.member_id}


@app.get("/", response_class=HTMLResponse)
async def home(user_id: CurrentUserId = storage.LOCAL_USER_ID) -> str:
    connected = storage.get_slack_token(user_id) is not None
    return f"""
    <html>
      <body style="font-family: sans-serif; max-width: 760px; margin: 40px auto;">
        <h1>QA Testcase Slack Integration</h1>
        <p>Slack connected: <strong>{connected}</strong></p>
        <p><a href="/slack/oauth/start">Connect Slack</a></p>
        <p><a href="/app">Open QA workspace</a></p>
        <p><a href="/generator">Open testcase generator</a></p>
      </body>
    </html>
    """


@app.get("/generator")
async def generator() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "generator.html", media_type="text/html")


@app.get("/slack/oauth/start")
async def slack_oauth_start(user_id: CurrentUserId = storage.LOCAL_USER_ID) -> RedirectResponse:
    """Begin authorization for the signed-in user.

    The state is stored against that user, so the callback can only bind a
    token to whoever started this specific flow.
    """
    try:
        url, state = build_authorize_url()
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing env var: {exc.args[0]}") from exc
    slack_oauth_state_migration.issue_state(storage.DB_PATH, user_id, state)
    return RedirectResponse(url)

@app.get("/slack/oauth/callback", response_class=HTMLResponse)
async def slack_oauth_callback(code: str, state: str) -> str:
    user_id = slack_oauth_state_migration.consume_state(storage.DB_PATH, state)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    data = await exchange_code(code)
    authed_user = data.get("authed_user") or {}
    token = authed_user.get("access_token")
    if not token:
        raise HTTPException(status_code=500, detail="Slack did not return a user access token")

    # One token per user row: two people authorizing never share a token.
    storage.save_slack_token(
        user_id,
        token,
        slack_user_id=authed_user.get("id"),
        team_id=(data.get("team") or {}).get("id"),
        scopes=data.get("scope") or authed_user.get("scope"),
    )
    return '<p>Slack connected. <a href="/">Back</a></p>'


def require_slack_token(user_id: int = storage.LOCAL_USER_ID) -> str:
    token = storage.get_slack_token(user_id)
    if not token:
        raise HTTPException(status_code=401, detail="Connect Slack first")
    return token


@app.post("/slack/send", response_class=HTMLResponse)
async def slack_send(text: str = Form(...), user_id: CurrentUserId = storage.LOCAL_USER_ID) -> str:
    user_token = require_slack_token(user_id)
    channel_id = os.getenv("SLACK_CHANNEL_ID")
    if not channel_id:
        raise HTTPException(status_code=500, detail="Missing SLACK_CHANNEL_ID")
    result = await post_message(user_token, channel_id, text)
    ts = result.get("ts", "unknown")
    return f'<p>Sent to Slack. ts={ts}</p><p><a href="/">Back</a></p>'


@app.post("/slack/events", include_in_schema=False)
async def slack_events_endpoint(request: Request) -> JSONResponse:
    """Slack Events API receiver.

    Public by design (Slack posts from its own servers), so the request is
    authenticated by the signing secret instead of the local-access middleware.
    Slack requires an answer within three seconds; the work here is a few
    SQLite statements, so it stays synchronous and fast.
    """
    body = await request.body()
    try:
        slack_events.verify_signature(
            os.getenv("SLACK_SIGNING_SECRET"),
            request.headers.get("x-slack-request-timestamp"),
            request.headers.get("x-slack-signature"),
            body,
        )
    except slack_events.SignatureError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=401)

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)

    if payload.get("type") == "url_verification":
        # Slack checks the URL before enabling subscriptions.
        return JSONResponse({"challenge": payload.get("challenge", "")})

    result = slack_events.handle_event(
        payload, retry_num=request.headers.get("x-slack-retry-num"),
    )
    return JSONResponse({"ok": True, **result})


@app.post("/slack/send-cases")
async def slack_send_cases(payload: SendCasesRequest, user_id: CurrentUserId = storage.LOCAL_USER_ID) -> dict:
    user_token = require_slack_token(user_id)

    if not payload.cases:
        raise HTTPException(status_code=400, detail="No generated cases")

    try:
        channel_id, _ = get_slack_route(payload.region)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        # No fallback to a default list: an empty selection mentions nobody.
        user_ids = normalize_mentions(payload.mention_users or [])
        mentions = format_mentions(user_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    operation = "выплаты" if payload.operation == "payout" else "депозита"
    request_text = payload.request_text.strip() if payload.request_text is not None else f"Просьба провести тест {operation}."

    slack_history.validate_case_ids((case_id for case in payload.cases for case_id in case.case_ids), user_id)
    deliveries = []
    sent = 0
    thread_ts_values: list[str] = []

    for case in payload.cases:
        case_request = case.request_text.strip() if case.request_text is not None else "\n".join(part for part in [request_text, case.title] if part)
        parent_text = " ".join(part for part in [mentions, case_request] if part)
        parent = await post_message(user_token, channel_id, parent_text or case.title)
        thread_ts = parent.get("ts")
        if not thread_ts:
            raise HTTPException(status_code=500, detail="Slack did not return parent message ts")

        message = f"{case.title}\n\n{case.text}"
        posted_case = await post_message(user_token, channel_id, message, thread_ts=thread_ts)
        if case.case_ids:
            # Commit channel/ts before lookup (or the optional instructions reply).
            # `thread_ts` is what Slack sends back on every reply in this thread.
            send_id = slack_history.record_send(
                case.case_ids, posted_case, user_id, thread_ts=thread_ts, own_ts=[thread_ts],
            )
            delivery = await slack_history.resolve_permalink(user_token, send_id, user_id)
            deliveries.append({**delivery, "case_ids": list(dict.fromkeys(case.case_ids))})

        if case.comment.strip():
            posted_note = await post_message(
                user_token, channel_id,
                f"Дополнительная информация:\n{case.comment.strip()}",
                thread_ts=thread_ts,
            )
            if case.case_ids:
                # Our own note must not come back as a "reply".
                slack_history.append_own_message(send_id, posted_note.get("ts"), user_id)

        if case.licence:
            build = webview_apk.read_apk(case.licence)
            if build:
                uploaded = await upload_file(
                    user_token, channel_id, build["filename"], build["content"],
                    thread_ts=thread_ts,
                    initial_comment=f"APK WebView ({case.licence}) · загружен {build['uploaded_at'][:10]}",
                )
                if case.case_ids:
                    # The attached file is ours; do not read it back as a reply.
                    for file in uploaded.get("files") or []:
                        slack_history.append_own_message(send_id, file.get("id"), user_id)
        thread_ts_values.append(thread_ts)
        sent += 1

    return {
        "ok": True,
        "sent": sent,
        "channel_id": channel_id,
        "mentioned_users": user_ids,
        "thread_ts": thread_ts_values,
        "deliveries": deliveries,
    }


