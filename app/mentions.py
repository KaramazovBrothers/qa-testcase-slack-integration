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
    """Accept a member ID, a profile link, <@U…> or a username; store the ID part."""
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

        if not USERNAME.fullmatch(value):
            if " " in value:
                raise ValueError(
                    f"'{value}' looks like a Slack display name or a link we do not "
                    "recognise. Paste the profile link (Copy link on the person in "
                    "Slack), the member ID (U0123456789) or a username without spaces."
                )
            raise ValueError(
                f"'{value}' is not a valid mention. Paste a Slack profile link, a "
                "member ID (U0123456789) or a username without spaces."
            )

        if value.lower() in {"@here", "@channel", "@everyone"}:
            raise ValueError("Specify individual people, not @here, @channel or @everyone")

        handle = value.lstrip("@")
        if handle not in result:
            result.append(handle)
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
    return " ".join(f"<@{value}>" if re.fullmatch(r"[UW][A-Z0-9]+", value) else f"@{value}" for value in normalize_mentions(values))
