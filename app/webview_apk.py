"""Shared WebView APK library and the people asked for a fresh build.

One build per licence, replaced on every upload: a tester always downloads the
newest file, and the upload date next to it says how old that file is. Everyone
uses the same library, so no row is scoped to a user.

The people list belongs to one Slack channel (the WebView request channel), not
to a region, so it is stored separately from `slack_people`.
"""

from datetime import datetime, timezone
from typing import Optional

from app import storage

LICENCES = ("com", "pinco", "zazino")
CHANNEL = "C07RKCUN132"
MAX_BYTES = 200 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_apk(licence: str, filename: str, content: bytes, user_id: Optional[int]) -> dict:
    """Store the build for one licence, replacing the previous one."""
    if licence not in LICENCES:
        raise ValueError(f"Unknown licence: {licence}")
    if not content:
        raise ValueError("The uploaded file is empty")
    if len(content) > MAX_BYTES:
        raise ValueError("The uploaded file is too large")

    stamp = _now()
    with storage.connection() as db:
        db.execute(
            """INSERT INTO webview_apks(licence,filename,size_bytes,content,uploaded_at,uploaded_by)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(licence) DO UPDATE SET
                   filename=excluded.filename,
                   size_bytes=excluded.size_bytes,
                   content=excluded.content,
                   uploaded_at=excluded.uploaded_at,
                   uploaded_by=excluded.uploaded_by""",
            (licence, filename, len(content), content, stamp, user_id),
        )
    return {"licence": licence, "filename": filename, "size_bytes": len(content),
            "uploaded_at": stamp}


def list_apks() -> list[dict]:
    """Every licence with its build, newest upload time first for the UI."""
    with storage.connection() as db:
        rows = db.execute(
            """SELECT licence, filename, size_bytes, uploaded_at
               FROM webview_apks ORDER BY uploaded_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def read_apk(licence: str) -> Optional[dict]:
    """The stored file plus its metadata, or None when nothing was uploaded."""
    with storage.connection() as db:
        row = db.execute(
            """SELECT licence, filename, size_bytes, content, uploaded_at
               FROM webview_apks WHERE licence=?""",
            (licence,),
        ).fetchone()
    return dict(row) if row else None


def delete_apk(licence: str) -> bool:
    with storage.connection() as db:
        cursor = db.execute("DELETE FROM webview_apks WHERE licence=?", (licence,))
    return cursor.rowcount > 0


# --- people of the WebView channel -------------------------------------------

def channel_people(channel: str = CHANNEL) -> list[dict]:
    """People to tag when asking for a build, stable order by name."""
    with storage.connection() as db:
        rows = db.execute(
            """SELECT slack_user_id, name FROM channel_people WHERE channel=?
               ORDER BY (name=''), name COLLATE NOCASE, slack_user_id""",
            (channel,),
        ).fetchall()
    return [{"id": row["slack_user_id"], "name": row["name"]} for row in rows]


def remember_channel_person(member_id: str, name: str, channel: str = CHANNEL) -> None:
    with storage.connection() as db:
        db.execute(
            """INSERT INTO channel_people(channel,slack_user_id,name,created_at)
               VALUES(?,?,?,?)
               ON CONFLICT(channel,slack_user_id) DO UPDATE SET name=excluded.name""",
            (channel, member_id, name or "", _now()),
        )


def forget_channel_person(member_id: str, channel: str = CHANNEL) -> bool:
    with storage.connection() as db:
        cursor = db.execute(
            "DELETE FROM channel_people WHERE channel=? AND slack_user_id=?",
            (channel, member_id),
        )
    return cursor.rowcount > 0


def request_message(licences: list[str], mentions: list[str]) -> str:
    """The text posted to the channel for a set of licences."""
    tags = " ".join(f"<@{member_id}>" for member_id in mentions)
    names = ", ".join(licences)
    line = f"Привет! Скинь, пожалуйста, свежую сборку ПРОД для {names}"
    return f"{tags} {line}".strip()
