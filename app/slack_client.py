import time

import httpx

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

# Slack answers these when the person must authorize the app again. They are
# kept distinct from ordinary failures so the caller can forget the token
# instead of showing the same error on every request.
TOKEN_REVOKED_ERRORS = {
    "token_revoked", "token_expired", "invalid_auth", "not_authed",
    "account_inactive", "user_is_bot", "missing_scope",
}


class SlackTokenRejected(RuntimeError):
    """The stored user token is no longer usable; reconnect Slack."""

    def __init__(self, error: str):
        super().__init__(
            "Slack token rejected (" + (error or "unknown_error") +
            "). Reconnect Slack to authorize this app again."
        )
        self.error = error


def token_rejected(error) -> SlackTokenRejected | None:
    return SlackTokenRejected(str(error)) if str(error) in TOKEN_REVOKED_ERRORS else None


async def post_message(
    user_token: str,
    channel_id: str,
    text: str,
    thread_ts: str | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {user_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"channel": channel_id, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(SLACK_POST_MESSAGE_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    if not data.get("ok"):
        error = data.get("error", "unknown_error")
        raise token_rejected(error) or RuntimeError(f"Slack API failed: {error}")
    return data


async def get_permalink(user_token: str, channel_id: str, message_ts: str) -> str:
    """Resolve an existing message; never post or retry a message here."""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            'https://slack.com/api/chat.getPermalink',
            headers={'Authorization': f'Bearer {user_token}'},
            params={'channel': channel_id, 'message_ts': message_ts},
        )
        response.raise_for_status()
        data = response.json()
    if not data.get('ok'):
        raise RuntimeError('Slack permalink lookup failed')
    permalink = data.get('permalink')
    return _validated_permalink(permalink)


async def channel_messages_with_replies(user_token: str, channel_id: str) -> list[dict]:
    """Channel messages of the last week that carry a thread.

    Used only when a recorded thread no longer resolves in Slack: the case body
    may still sit in the channel as a root message, and this lets the delete
    find it instead of leaving it behind.
    """
    oldest = str(int(time.time()) - 7 * 24 * 3600)
    found: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as client:
        cursor = None
        for _ in range(5):  # five pages of 200 messages is far beyond a QA day
            params = {'channel': channel_id, 'limit': 200, 'oldest': oldest}
            if cursor:
                params['cursor'] = cursor
            response = await client.get(
                'https://slack.com/api/conversations.history',
                headers={'Authorization': f'Bearer {user_token}'},
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            if not data.get('ok'):
                raise RuntimeError(f"Slack history failed: {data.get('error', 'unknown_error')}")
            found.extend(m for m in data.get('messages') or [] if m.get('thread_ts'))
            cursor = (data.get('response_metadata') or {}).get('next_cursor')
            if not cursor:
                break
    return found


def _validated_permalink(permalink) -> str:
    from urllib.parse import urlsplit
    if not isinstance(permalink, str):
        raise ValueError('Slack did not return a permalink')
    url = urlsplit(permalink)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or not any(url.hostname == domain or url.hostname.endswith('.' + domain)
                       for domain in ('slack.com', 'slack-gov.com'))):
        raise ValueError('Slack returned an invalid permalink')
    return permalink


async def list_thread_replies(user_token: str, channel_id: str, thread_ts: str) -> list[dict]:
    """Every message in a thread except the parent, oldest first.

    Slack pages replies 1 MB at a time; a case thread is short, but the cursor
    loop keeps a long hand-written discussion from being half-read.
    """
    messages: list[dict] = []
    cursor = None
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            params = {'channel': channel_id, 'ts': thread_ts, 'limit': 200}
            if cursor:
                params['cursor'] = cursor
            response = await client.get(
                'https://slack.com/api/conversations.replies',
                headers={'Authorization': f'Bearer {user_token}'},
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            if not data.get('ok'):
                raise RuntimeError(f"Slack replies failed: {data.get('error', 'unknown_error')}")
            messages.extend(m for m in data.get('messages') or [] if m.get('ts') != thread_ts)
            cursor = (data.get('response_metadata') or {}).get('next_cursor')
            if not cursor:
                break
    return messages


async def delete_message(user_token: str, channel_id: str, message_ts: str) -> dict:
    """Delete one message; return Slack's answer instead of raising.

    `cant_delete_message` (a reply written by another person) is a normal
    outcome here, so the caller can report what stayed instead of failing.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            'https://slack.com/api/chat.delete',
            headers={'Authorization': f'Bearer {user_token}',
                     'Content-Type': 'application/json; charset=utf-8'},
            json={'channel': channel_id, 'ts': message_ts},
        )
        response.raise_for_status()
        return response.json()

async def upload_file(user_token: str, channel_id: str, filename: str,
                      content: bytes, *, thread_ts: str | None = None,
                      initial_comment: str = "") -> dict:
    """Upload a binary to a channel or thread.

    Slack retired files.upload; the current flow asks for an upload URL, sends
    the bytes there, then completes the upload against the channel. Each step
    can fail on its own, so the caller gets the message that names it.
    """
    headers = {"Authorization": f"Bearer {user_token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        opened = (await client.get(
            "https://slack.com/api/files.getUploadURLExternal", headers=headers,
            params={"filename": filename, "length": len(content)},
        )).json()
        if not opened.get("ok"):
            raise RuntimeError(f"Slack upload URL failed: {opened.get('error', 'unknown_error')}")

        sent = await client.post(
            opened["upload_url"], files={"file": (filename, content)},
        )
        sent.raise_for_status()

        payload = {"files": [{"id": opened["file_id"], "title": filename}]}
        if channel_id:
            payload["channel_id"] = channel_id
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if initial_comment:
            payload["initial_comment"] = initial_comment
        completed = (await client.post(
            "https://slack.com/api/files.completeUploadExternal",
            headers={**headers, "Content-Type": "application/json; charset=utf-8"},
            json=payload,
        )).json()
    if not completed.get("ok"):
        raise RuntimeError(f"Slack upload failed: {completed.get('error', 'unknown_error')}")
    return completed

