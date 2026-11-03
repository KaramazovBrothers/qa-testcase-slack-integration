import json
import re
from pathlib import Path

MENTIONS_PATH = Path(__file__).resolve().parent.parent / "config" / "region_mentions.json"

# Slack member IDs are `U…` for people and `W…` for enterprise users.
MEMBER_ID = re.compile(r"[UW][A-Z0-9]{2,}")
# A profile URL such as https://team.slack.com/team/U04BNNL48KF ends with the ID.
PROFILE_URL = re.compile(r"https?://[^/\s]+(?:\.slack\.com)?/team/([UW][A-Z0-9]+)/?")
# Bare usernames may contain dots, dashes and underscores but never spaces.
USERNAME = re.compile(r"@?[A-Za-z0-9_.-]{1,80}")


def extract_member_id(value: str) -> str | None:
    """Pull a member ID out of a profile link, an <@U…> reference or a bare ID.

    Copying the link from Slack is easier than finding "Copy member ID" in the
    profile menu, and both must lead to the same stored value.
    """
    text = value.strip()
    link = PROFILE_URL.search(text)
    if link:
        return link.group(1)
    reference = re.fullmatch(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>", text)
    if reference:
        return reference.group(1)
    bare = text.lstrip("@")
    if MEMBER_ID.fullmatch(bare):
        return bare
    return None


def normalize_mentions(values: list[str]) -> list[str]:
    """Accept a member ID, a profile link, <@U…> or a username.

    Anything else is passed through untouched: a display name such as
    "@Dzmitryi Karaliou" cannot notify anyone, but rejecting it made saving
    impossible and hid the real problem. `format_mentions` still renders IDs as
    `<@U…>` and everything else as plain text.
    """
    result = []
    for value in values:
        value = value.strip()
        if not value:
            continue

        member_id = extract_member_id(value)
        if member_id:
            if member_id not in result:
                result.append(member_id)
            continue

        if value.lower() in {"@here", "@channel", "@everyone"}:
            raise ValueError("Specify individual people, not @here, @channel or @everyone")
        # Slack's raw broadcast syntax reaches everyone in the channel.
        if value.strip().lower() in {"<!here>", "<!channel>", "<!everyone>",
                                     "<!here|here>", "<!channel|channel>",
                                     "<!everyone|everyone>"}:
            raise ValueError("Specify individual people, not a channel-wide broadcast")

        # Unknown shapes are kept verbatim so the workspace keeps working.
        if value not in result:
            result.append(value)
    return result


def load_region_mentions() -> dict[str, list[str]]:
    with MENTIONS_PATH.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict) or any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in data.values()):
        raise ValueError("Invalid region mentions configuration")
    for values in data.values():
        normalize_mentions(values)
    return data


def format_mentions(values: list[str]) -> str:
    """Render mentions for `chat.postMessage`.

    A member id becomes `<@U…>` so Slack notifies the person. Usernames lose
    their leading `@` before being re-prefixed, and anything else (a display
    name kept verbatim by `normalize_mentions`) is passed through as text.
    """
    parts = []
    for value in normalize_mentions(values):
        if MEMBER_ID.fullmatch(value):
            parts.append(f"<@{value}>")
        elif USERNAME.fullmatch(value):
            parts.append("@" + value.lstrip("@"))
        else:
            parts.append(value)
    return " ".join(parts)
