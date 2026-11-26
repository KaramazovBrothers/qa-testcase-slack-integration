"""Which Slack channel and who to mention for a region.

The configuration lives in `config/slack_routes.json` and nowhere else: each
region must name its own channel and its own people. There is deliberately no
"default" entry and no environment fallback, because sending a QA request to a
guessed channel, or pinging a guessed person, is worse than refusing to send.

The file is environment-specific and git-ignored; `slack_routes.example.json`
shows the shape.
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ROUTES_PATH = BASE_DIR / "config" / "slack_routes.json"


class RouteNotConfigured(RuntimeError):
    """The region has no explicit Slack route; sending must stop."""


def _load_routes() -> dict:
    with ROUTES_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_slack_route(region: str) -> tuple[str, list[str]]:
    """Channel and mentions for `region`, exactly as configured.

    Raises `RouteNotConfigured` when the file is missing, the region is absent,
    or the entry has no channel. An empty mention list is allowed and means
    "post without pinging anyone"; a missing channel never is.
    """
    if not ROUTES_PATH.exists():
        raise RouteNotConfigured(
            "config/slack_routes.json is missing: every region must name its Slack channel"
        )

    routes = _load_routes()
    route = routes.get(region)
    if not isinstance(route, dict):
        raise RouteNotConfigured(
            f"Region {region} has no Slack route in config/slack_routes.json"
        )

    channel_id = str(route.get("channel_id") or "").strip()
    if not channel_id:
        raise RouteNotConfigured(
            f"Region {region} has no channel_id in config/slack_routes.json"
        )

    configured_users = route.get("user_ids")
    if configured_users is None:
        raise RouteNotConfigured(
            f"Region {region} has no user_ids list in config/slack_routes.json"
        )
    if not isinstance(configured_users, list):
        raise RouteNotConfigured(
            f"Region {region} has user_ids that is not a list in config/slack_routes.json"
        )

    return channel_id, [str(item).strip() for item in configured_users if str(item).strip()]
