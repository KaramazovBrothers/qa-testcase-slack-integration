import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ROUTES_PATH = BASE_DIR / "config" / "slack_routes.json"


def _env_user_ids() -> list[str]:
    raw = os.getenv("SLACK_MENTION_USER_IDS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def get_slack_route(region: str) -> tuple[str, list[str]]:
    channel_id = os.getenv("SLACK_CHANNEL_ID", "").strip()
    user_ids = _env_user_ids()

    if ROUTES_PATH.exists():
        with ROUTES_PATH.open("r", encoding="utf-8") as file:
            routes = json.load(file)

        route = routes.get(region) or routes.get("default") or {}
        channel_id = str(route.get("channel_id") or channel_id).strip()
        configured_users = route.get("user_ids")
        if configured_users is not None:
            user_ids = [str(item).strip() for item in configured_users if str(item).strip()]

    if not channel_id:
        raise RuntimeError(f"No Slack channel configured for region {region}")

    return channel_id, user_ids
