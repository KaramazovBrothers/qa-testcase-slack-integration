"""WebView APK library: upload, list, download, delete, and build requests."""

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app import storage, webview_apk
from app.current_user import CurrentUserId
from app.slack_client import post_message

router = APIRouter(prefix="/api/webview", tags=["WebView builds"])


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PersonInput(Model):
    entry: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=200)


class RequestInput(Model):
    licences: list[str] = Field(min_length=1, max_length=len(webview_apk.LICENCES))


@router.get("/apks")
def list_apks() -> dict:
    """Builds on file, with the upload date the UI shows next to each licence."""
    stored = {row["licence"]: row for row in webview_apk.list_apks()}
    return {
        "licences": [
            stored.get(licence) or {"licence": licence, "filename": None,
                                   "size_bytes": None, "uploaded_at": None}
            for licence in webview_apk.LICENCES
        ]
    }


@router.post("/apks", status_code=201)
async def upload_apk(
    licence: str = Form(...),
    file: UploadFile = File(...),
    user_id: CurrentUserId = storage.LOCAL_USER_ID,
) -> dict:
    content = await file.read()
    try:
        return webview_apk.save_apk(licence, file.filename or "webview.apk", content, user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/apks/{licence}")
def download_apk(licence: str) -> Response:
    row = webview_apk.read_apk(licence)
    if not row:
        raise HTTPException(404, "No build uploaded for this licence")
    return Response(
        content=row["content"],
        media_type="application/vnd.android.package-archive",
        headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'},
    )


@router.delete("/apks/{licence}", status_code=204)
def delete_apk(licence: str) -> Response:
    if not webview_apk.delete_apk(licence):
        raise HTTPException(404, "No build uploaded for this licence")
    return Response(status_code=204)


@router.get("/people")
def list_people() -> dict:
    """Who gets tagged in a build request for this channel."""
    people = webview_apk.channel_people()
    return {"channel": webview_apk.CHANNEL, "people": people}


@router.post("/people", status_code=201)
async def add_person(payload: PersonInput, user_id: CurrentUserId = storage.LOCAL_USER_ID) -> dict:
    from app.mentions import normalize_mentions
    from app import slack_people

    try:
        member_ids = normalize_mentions([payload.entry])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not member_ids:
        raise HTTPException(400, "No person to add")

    member_id = member_ids[0]
    name = payload.name.strip()
    if not name:
        token = storage.get_slack_token(user_id)
        name = (await slack_people.resolve(token, member_id) or "").strip()
    webview_apk.remember_channel_person(member_id, name)
    return {"ok": True, "id": member_id, "name": name}


@router.delete("/people/{member_id}", status_code=204)
def remove_person(member_id: str) -> Response:
    if not webview_apk.forget_channel_person(member_id):
        raise HTTPException(404, "Person not found in this channel list")
    return Response(status_code=204)


@router.post("/request")
async def request_build(payload: RequestInput, user_id: CurrentUserId = storage.LOCAL_USER_ID) -> dict:
    """Post "send a fresh build" to the WebView channel for each licence."""
    unknown = [item for item in payload.licences if item not in webview_apk.LICENCES]
    if unknown:
        raise HTTPException(422, f"Unknown licence: {', '.join(unknown)}")

    token = storage.get_slack_token(user_id)
    if not token:
        raise HTTPException(401, "Connect Slack first")

    people = webview_apk.channel_people()
    mentions = [person["id"] for person in people]
    # One message per licence keeps the reply threads separate.
    sent = []
    for licence in payload.licences:
        text = webview_apk.request_message([licence], mentions)
        result = await post_message(token, webview_apk.CHANNEL, text)
        sent.append({"licence": licence, "ts": result.get("ts"), "channel": webview_apk.CHANNEL})
    return {"sent": sent, "channel": webview_apk.CHANNEL,
            "tagged": [person["id"] for person in people]}
