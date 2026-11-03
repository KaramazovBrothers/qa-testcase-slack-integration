"""Resolve Slack member IDs to display names so the UI shows a person, not `U…`.

Slack is the only source of truth for a name, so the lookup is an API call.
Results are cached in `slack_people` (schema v8): rendering a form must never
wait on the network, and an offline Slack must not break the workspace.

A failed lookup is not an error the user has to act on: the ID is stored as
before and the name simply stays unknown until a later refresh succeeds.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app import storage

SLACK_USERS_INFO_URL = "https://slack.com/api/users.info"
CACHE_TTL = timedelta(days=1)



def _now() -> datetime:
    return datetime.now(timezone.utc)


def display_name(user: dict) -> str:
    """Prefer the name a human recognises, matching what Slack shows in a chat."""
    profile = user.get("profile") or {}
    for candidate in (
        profile.get("display_name"),
        user.get("real_name"),
        profile.get("real_name"),
        user.get("name"),
    ):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return ""


async def fetch_user(token: str, member_id: str) -> Optional[dict]:
    """Fetch one member from Slack; None when it cannot be read."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                SLACK_USERS_INFO_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={"user": member_id},
            )
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not data.get("ok"):
        # missing_scope, user_not_found, invalid_auth: keep the ID, show no name.
        return None
    return data.get("user")


def cached(member_id: str) -> Optional[str]:
    with storage.connection() as db:
        row = db.execute(
            "SELECT name, fetched_at FROM slack_people WHERE slack_user_id=?",
            (member_id,),
        ).fetchone()
    if row is None or not row["name"]:
        return None
    return row["name"]


def is_stale(member_id: str) -> bool:
    with storage.connection() as db:
        row = db.execute(
            "SELECT fetched_at FROM slack_people WHERE slack_user_id=?",
            (member_id,),
        ).fetchone()
    if row is None or not row["fetched_at"]:
        return True
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except ValueError:
        return True
    return _now() - fetched > CACHE_TTL


def remember(member_id: str, name: str, *, team_id: Optional[str] = None) -> None:
    with storage.connection() as db:
        db.execute(
            """INSERT INTO slack_people(slack_user_id,name,team_id,fetched_at)
               VALUES(?,?,?,?)
               ON CONFLICT(slack_user_id) DO UPDATE SET
                   name=excluded.name,
                   team_id=coalesce(excluded.team_id, slack_people.team_id),
                   fetched_at=excluded.fetched_at""",
            (member_id, name, team_id, _now().isoformat()),
        )


async def resolve(token: Optional[str], member_id: str, *, refresh: bool = False) -> Optional[str]:
    """Return a display name from the cache, or ask Slack when it is missing."""
    if not refresh:
        name = cached(member_id)
        if name and not is_stale(member_id):
            return name
    if not token:
        return cached(member_id)
    user = await fetch_user(token, member_id)
    if user is None:
        return cached(member_id)
    name = display_name(user)
    if name:
        remember(member_id, name, team_id=user.get("team_id"))
    return name or cached(member_id)


def all_cached() -> dict[str, str]:
    """Every known name, for the UI to render a list without extra calls."""
    with storage.connection() as db:
        rows = db.execute("SELECT slack_user_id, name FROM slack_people").fetchall()
    return {row["slack_user_id"]: row["name"] for row in rows if row["name"]}
