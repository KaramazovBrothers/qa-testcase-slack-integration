import httpx

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


async def post_message(user_token: str, channel_id: str, text: str) -> dict:
    headers = {
        "Authorization": f"Bearer {user_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"channel": channel_id, "text": text}

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(SLACK_POST_MESSAGE_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    if not data.get("ok"):
        raise RuntimeError(f"Slack API failed: {data.get('error', 'unknown_error')}")
    return data
