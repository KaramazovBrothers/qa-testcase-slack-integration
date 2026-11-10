"""Push Slack thread replies to the browser as they arrive.

Polling made the UI lag behind Slack by up to one interval. The Events API
already tells us the moment a reply lands, so the workspace subscribes over
Server-Sent Events and redraws immediately.

An in-memory queue alone only works while every request is handled by the same
process. Slack posts events to whichever worker it reaches, so the reply is also
filed in `slack_stream_events`; a stream replays what it missed on connect and
the Events API worker broadcasts to whoever is listening to it.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from app import storage

# Subscribers are plain asyncio queues. A slow or vanished tab must never block
# the Events API, so publishing never awaits: it drops the event for a full queue.
_subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop | None] = {}
_MAX_QUEUE = 100
# How long a stream replays replies it did not hear while it was disconnected.
REPLAY_WINDOW_SECONDS = 2 * 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_event(event: dict) -> None:
    """Keep a published event so a stream on another worker can replay it."""
    event_id = event.get("event_id")
    if not event_id:
        return
    with storage.connection() as db:
        db.execute(
            """INSERT OR IGNORE INTO slack_stream_events(event_id,payload,created_at)
               VALUES(?,?,?)""",
            (str(event_id), json.dumps(event, ensure_ascii=False), _now()),
        )


def replay(since_iso: str | None) -> list[dict]:
    """Events still worth replaying to a stream opened at `since_iso`."""
    floor = (datetime.now(timezone.utc) - timedelta(seconds=REPLAY_WINDOW_SECONDS)).isoformat()
    start = since_iso if since_iso and since_iso > floor else floor
    with storage.connection() as db:
        rows = db.execute(
            "SELECT payload FROM slack_stream_events WHERE created_at>=? ORDER BY id",
            (start,),
        ).fetchall()
    events = []
    for row in rows:
        try:
            events.append(json.loads(row["payload"]))
        except (TypeError, ValueError):
            continue
    return events


def prune(before_iso: str | None = None) -> int:
    """Drop events older than the replay window; returns the number deleted."""
    floor = before_iso or (datetime.now(timezone.utc) - timedelta(seconds=REPLAY_WINDOW_SECONDS)).isoformat()
    with storage.connection() as db:
        return db.execute("DELETE FROM slack_stream_events WHERE created_at<?", (floor,)).rowcount


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        # Subscribed outside a loop (tests, scripts): deliver inline instead.
        loop = None
    _subscribers[queue] = loop
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _subscribers.pop(queue, None)


def _deliver(queue: asyncio.Queue, event: dict) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        # The tab stopped reading: drop the oldest and keep the newest.
        try:
            queue.get_nowait()
            queue.put_nowait(event)
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass


def publish(event: dict) -> None:
    """Broadcast one event; safe to call from a sync Events API handler.

    `handle_event` is a plain function, so FastAPI runs it in a worker thread.
    `Queue.put_nowait` is not thread-safe and would not wake the loop waiting in
    `stream()`, so the delivery is handed back to each subscriber's own loop.
    """
    for queue, loop in list(_subscribers.items()):
        if loop is None:
            _deliver(queue, event)
            continue
        try:
            loop.call_soon_threadsafe(_deliver, queue, event)
        except RuntimeError:
            # The loop behind that tab is already closed.
            unsubscribe(queue)
    # Persist outside the subscriber loop: another worker owns the connection
    # that holds the open tab, and it replays this event on its next connect.
    file_event(event)


def publish_reply(send_id: int, case_ids: list[int], reply: dict, event_id: str | None = None) -> None:
    publish({
        "type": "reply",
        "event_id": event_id or f"reply-{send_id}-{reply.get('ts')}",
        "send_id": send_id,
        "case_ids": case_ids,
        "ts": reply.get("ts"),
        "author": reply.get("author_id"),
        "text": reply.get("text", ""),
        "received_at": reply.get("received_at"),
    })


async def stream(queue: asyncio.Queue, heartbeat: float = 20.0,
                 backlog: list[dict] | None = None) -> AsyncIterator[str]:
    """SSE frames for one subscriber; a comment keeps idle proxies awake."""
    try:
        yield "retry: 3000\n\n"
        for event in backlog or ():
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        unsubscribe(queue)


def subscriber_count() -> int:
    return len(_subscribers)
