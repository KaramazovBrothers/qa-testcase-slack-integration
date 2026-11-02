"""Slack Events API: signature verification and reply ingestion.

Slack cannot subscribe to individual threads. The app receives every
`message.channels` / `message.groups` event the user can see and this module
decides which ones belong to a case we sent.

Filtering rules, in order:
  1. HTTP level: verify the request signature and the timestamp window.
  2. Slack envelope: ignore retries (`x-slack-retry-num`), URL verification,
     bot/app messages and edits.
  3. Ownership: the (channel, thread_ts) pair must match a recorded send.
  4. Self-authored messages: skipped by message ts, not by author, because the
     same person may legitimately answer in the thread later.
  5. Deduplication: one event_id is processed at most once.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

from app import storage

VERSION = "v0"
MAX_CLOCK_SKEW_SECONDS = 5 * 60
SUPPORTED_EVENTS = {"message"}


class SignatureError(ValueError):
    """Raised when a request is not provably from Slack."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """Slack's `v0=` HMAC-SHA256 signature over `v0:{ts}:{body}`."""
    basestring = b":".join([VERSION.encode(), timestamp.encode(), body])
    digest = hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    return f"{VERSION}={digest}"


def verify_signature(
    secret: str | None,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    *,
    clock=time.time,
    max_skew: int = MAX_CLOCK_SKEW_SECONDS,
) -> None:
    """Validate a Slack request, raising SignatureError on any problem.

    Uses a constant-time comparison and rejects timestamps outside the replay
    window Slack documents.
    """
    if not secret:
        raise SignatureError("SLACK_SIGNING_SECRET is not configured")
    if not timestamp or not signature:
        raise SignatureError("Missing signature headers")
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise SignatureError("Malformed timestamp") from exc
    if abs(clock() - sent_at) > max_skew:
        raise SignatureError("Timestamp outside the allowed window")
    expected = sign(secret, timestamp, body)
    if not hmac.compare_digest(expected, signature):
        raise SignatureError("Signature mismatch")


def _seen(event_id: str | None) -> bool:
    if not event_id:
        return False
    with storage.connection() as db:
        return db.execute(
            "SELECT 1 FROM slack_events WHERE event_id=?", (event_id,)
        ).fetchone() is not None


def _remember(event_id: str | None, event_type: str, outcome: str) -> None:
    if not event_id:
        return
    with storage.connection() as db:
        db.execute(
            "INSERT OR IGNORE INTO slack_events(event_id,event_type,received_at,outcome) VALUES(?,?,?,?)",
            (event_id, event_type, now(), outcome),
        )


def _send_for_thread(channel: str, thread_ts: str):
    with storage.connection() as db:
        return db.execute(
            "SELECT * FROM slack_sends WHERE channel=? AND thread_ts=? ORDER BY id LIMIT 1",
            (channel, thread_ts),
        ).fetchone()


def is_own_message(row, ts: str) -> bool:
    """True when the message was posted by the app itself."""
    own = json.loads(row["own_ts"] or "[]")
    return ts in own or ts == row["ts"]


def _save_reply(row, event: dict) -> bool:
    """Store a reply once; returns False when it was already known."""
    with storage.connection() as db:
        cursor = db.execute(
            """INSERT OR IGNORE INTO slack_replies
               (send_id,event_id,channel,thread_ts,ts,author_id,author_name,text,received_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                row["id"],
                event.get("client_msg_id"),
                event.get("channel", ""),
                event.get("thread_ts") or "",
                event.get("ts") or "",
                event.get("user"),
                None,
                event.get("text") or "",
                now(),
            ),
        )
        return cursor.rowcount > 0


def handle_event(payload: dict, *, retry_num: str | None = None) -> dict:
    """Process one Events API payload.

    Returns a small status dict; the HTTP layer answers 200 even for payloads
    it ignores, so Slack does not retry something we will never accept.
    """
    if payload.get("type") == "url_verification":
        return {"status": "challenge"}

    event_id = payload.get("event_id")
    event = payload.get("event") or {}
    event_type = event.get("type", "")

    if retry_num:
        # Slack retries when the first answer was too slow; processing the same
        # payload twice would duplicate replies.
        _remember(event_id, event_type, "retry-ignored")
        return {"status": "ignored", "reason": "retry"}

    if event_type not in SUPPORTED_EVENTS:
        return {"status": "ignored", "reason": "unsupported-event"}
    if event.get("subtype"):
        # bot_message, message_changed, message_deleted and friends.
        _remember(event_id, event_type, "subtype-ignored")
        return {"status": "ignored", "reason": "subtype"}
    if event.get("bot_id") or event.get("app_id"):
        _remember(event_id, event_type, "bot-ignored")
        return {"status": "ignored", "reason": "bot"}

    channel = event.get("channel")
    thread_ts = event.get("thread_ts")
    ts = event.get("ts")
    if not channel or not thread_ts or not ts:
        # Only replies inside a thread matter; a root message is our own send.
        return {"status": "ignored", "reason": "not-a-thread-reply"}

    row = _send_for_thread(channel, thread_ts)
    if row is None:
        return {"status": "ignored", "reason": "unknown-thread"}
    # Our own messages are recognised by ts before deduplication: Slack also
    # echoes what the app posts, and those echoes must never be stored.
    if is_own_message(row, ts):
        _remember(event_id, event_type, "own-message")
        return {"status": "ignored", "reason": "own-message"}
    if _seen(event_id):
        return {"status": "ignored", "reason": "duplicate-event"}

    created = _save_reply(row, event)
    _remember(event_id, event_type, "stored" if created else "duplicate-reply")
    return {"status": "stored" if created else "ignored", "send_id": row["id"]}


def replies_for_case(db, case_id: int) -> list[dict]:
    """Replies attached to a case, oldest first, for the UI."""
    rows = db.execute(
        """SELECT r.* FROM slack_replies r
           JOIN slack_send_cases link ON link.send_id=r.send_id
           WHERE link.case_id=? ORDER BY r.ts""",
        (case_id,),
    )
    return [dict(row) for row in rows]
