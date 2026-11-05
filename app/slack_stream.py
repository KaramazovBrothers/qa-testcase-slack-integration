"""Push Slack thread replies to the browser as they arrive.

Polling made the UI lag behind Slack by up to one interval. The Events API
already tells us the moment a reply lands, so the workspace subscribes over
Server-Sent Events and redraws immediately.

The bus is deliberately tiny and process-local: the app is a single loopback
server for one user, and a reply is only useful to that user's open tab.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

# Subscribers are plain asyncio queues. A slow or vanished tab must never block
# the Events API, so publishing never awaits: it drops the event for a full queue.
_subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop | None] = {}
_MAX_QUEUE = 100


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


def publish_reply(send_id: int, case_ids: list[int], reply: dict) -> None:
    publish({
        "type": "reply",
        "send_id": send_id,
        "case_ids": case_ids,
        "ts": reply.get("ts"),
        "author": reply.get("author_id"),
        "text": reply.get("text", ""),
        "received_at": reply.get("received_at"),
    })


async def stream(queue: asyncio.Queue, heartbeat: float = 20.0) -> AsyncIterator[str]:
    """SSE frames for one subscriber; a comment keeps idle proxies awake."""
    try:
        yield "retry: 3000\n\n"
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
