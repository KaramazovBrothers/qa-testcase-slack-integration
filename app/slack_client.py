import httpx

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


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
        raise RuntimeError(f"Slack API failed: {data.get('error', 'unknown_error')}")
    return data


async def get_permalink(user_token: str, channel_id: str, message_ts: str) -> str:
    """Resolve an existing message; never post or retry a message here."""
    from urllib.parse import urlsplit

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
    if not isinstance(permalink, str):
        raise ValueError('Slack did not return a permalink')
    url = urlsplit(permalink)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or not any(url.hostname == domain or url.hostname.endswith('.' + domain)
                       for domain in ('slack.com', 'slack-gov.com'))):
        raise ValueError('Slack returned an invalid permalink')
    return permalink
