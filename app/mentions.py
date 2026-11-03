import json
import re
from pathlib import Path

MENTIONS_PATH = Path(__file__).resolve().parent.parent / "config" / "region_mentions.json"


def normalize_mentions(values: list[str]) -> list[str]:
    result = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        if not re.fullmatch(r"@?[A-Za-z0-9_.-]{1,80}", value):
            if " " in value:
                raise ValueError(
                    f"'{value}' looks like a Slack display name. A display name "
                    "cannot notify anyone: Slack needs a member ID (U0123456789) "
                    "or a username without spaces. In Slack: open the person's "
                    "profile, click ⋮ and choose Copy member ID."
                )
            raise ValueError(
                f"'{value}' is not a valid mention. Use a Slack member ID "
                "(U0123456789) or a username without spaces."
            )
        if value.lower() in {"@here", "@channel", "@everyone"}:
            raise ValueError("Specify individual people, not @here, @channel or @everyone")
        value = value.lstrip("@")
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
    return " ".join(f"<@{value}>" if re.fullmatch(r"[UW][A-Z0-9]+", value) else f"@{value}" for value in normalize_mentions(values))
