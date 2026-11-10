"""Persist acknowledged Slack messages before attempting permalink resolution."""
import json
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from app import storage
from app.slack_client import (get_permalink, list_thread_replies, delete_message,
                              channel_messages_with_replies)


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_case_ids(case_ids, user_id=storage.LOCAL_USER_ID):
    """Validate the whole batch before any outbound Slack side effect."""
    ids = set(case_ids)
    if not ids:
        return
    with storage.connection() as db:
        for case_id in ids:
            if not db.execute('''SELECT 1 FROM test_cases c JOIN case_sets s ON s.id=c.set_id
                JOIN tasks t ON t.id=s.task_id WHERE c.id=? AND t.owner_user_id=?''', (case_id,user_id)).fetchone():
                raise HTTPException(404, 'Saved test case not found')


def record_send(case_ids, response, user_id=storage.LOCAL_USER_ID, thread_ts=None, own_ts=()):
    """Persist an acknowledged message.

    `thread_ts` is the parent message of the thread (Slack sends every reply in
    that thread with the same value) and `own_ts` lists the messages the app
    itself posted there, so replies can be filtered without looking at authors.
    """
    # ts must remain a string: float conversion loses Slack timestamp precision.
    channel, ts = response.get('channel'), response.get('ts')
    if not isinstance(channel, str) or not channel or not isinstance(ts, str) or not ts:
        raise HTTPException(502, 'Message posted, but Slack returned no channel/ts. Check Slack before sending again.')
    parent = thread_ts if isinstance(thread_ts, str) and thread_ts else ts
    posted = [value for value in dict.fromkeys([*own_ts, ts]) if isinstance(value, str) and value]
    with storage.connection() as db:
        cursor = db.execute(
            'INSERT INTO slack_sends(owner_user_id,channel,ts,sent_at,thread_ts,own_ts) VALUES(?,?,?,?,?,?)',
            (user_id, channel, ts, now(), parent, json.dumps(posted)),
        )
        send_id = cursor.lastrowid
        db.executemany('INSERT INTO slack_send_cases(send_id,case_id) VALUES(?,?)',
                       [(send_id, case_id) for case_id in set(case_ids)])
    return send_id


def append_own_message(send_id, ts, user_id=storage.LOCAL_USER_ID):
    """Remember another message the app posted in this thread.

    Order matters: the first entry is the thread start and the last one is the
    latest post. Two messages posted within the same second can share a Slack
    timestamp, so they are kept as distinct entries instead of being merged.
    """
    if not isinstance(ts, str) or not ts:
        return
    with storage.connection() as db:
        row = db.execute('SELECT own_ts FROM slack_sends WHERE id=? AND owner_user_id=?', (send_id, user_id)).fetchone()
        if row is None:
            return
        own = json.loads(row['own_ts'] or '[]')
        own.append(ts)
        db.execute('UPDATE slack_sends SET own_ts=? WHERE id=?', (json.dumps(own), send_id))


def read_send(send_id, user_id=storage.LOCAL_USER_ID):
    with storage.connection() as db:
        row = db.execute('SELECT * FROM slack_sends WHERE id=? AND owner_user_id=?', (send_id,user_id)).fetchone()
        if row is None:
            raise HTTPException(404, 'Slack send not found')
        return dict(row)


async def resolve_permalink(user_token, send_id, user_id=storage.LOCAL_USER_ID):
    record = read_send(send_id,user_id)
    if record['permalink']:
        return record
    try:
        permalink = await get_permalink(user_token, record['channel'], record['ts'])
    except (httpx.HTTPError, RuntimeError):
        # A lookup failure must never make an acknowledged post look unsent.
        # Do not persist exception text: it may contain request credentials.
        with storage.connection() as db:
            db.execute('UPDATE slack_sends SET permalink_error=?,permalink_checked_at=? WHERE id=? AND permalink IS NULL',
                       ('Link unavailable. Retry link lookup only; the message was already sent.', now(), send_id))
    else:
        with storage.connection() as db:
            db.execute('UPDATE slack_sends SET permalink=?,permalink_error=NULL,permalink_checked_at=? WHERE id=?',
                       (permalink, now(), send_id))
    return read_send(send_id,user_id)


class ThreadHasPeopleReplies(HTTPException):
    """Raised before anything is deleted when a person answered in the thread."""

    def __init__(self, count: int):
        super().__init__(
            409,
            f'В треде есть ответы людей ({count}). Удаление отменено: '
            'сообщение и тред в Slack остались без изменений.',
        )


class ThreadNotOursToDelete(HTTPException):
    """The recorded thread start never came from the app, so it stays."""

    def __init__(self):
        super().__init__(
            409,
            'Удаление отменено: записанный старт треда не принадлежит приложению. '
            'В Slack остались сообщения, поэтому запись сохранена: почистите тред вручную.',
        )


def posted_ts(record) -> str | None:
    """The timestamp of the case body, which is the case's root message.

    `slack_sends.ts` is the *thread start*: the request text when the case was
    sent on its own, or the case body when it shared a thread. The body is the
    message that really belongs to this send, so it is the one to fall back on.
    """
    stamps = _own_message_ts(record)
    thread_ts = record['thread_ts'] or record['ts']
    body = [value for value in stamps if value != thread_ts]
    if body:
        return max(body, key=float)
    return thread_ts if thread_ts in stamps else None


def _own_file_ids(record) -> set[str]:
    """File ids the app uploaded into this thread (APK, case screenshots)."""
    return {value for value in json.loads(record['own_ts'] or '[]')
            if isinstance(value, str) and value and not _looks_like_ts(value)}


def _looks_like_ts(value: str) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _own_message_ts(record) -> set[str]:
    """Everything in `own_ts` that is a message timestamp, not a file id.

    The same list also stores uploaded file ids (`F0CGLLK5517`), which are not
    timestamps and must never be compared with a message.
    """
    return {value for value in json.loads(record['own_ts'] or '[]')
            if isinstance(value, str) and value and _looks_like_ts(value)}


def _is_ours(record, message: dict, own: set[str]) -> bool:
    """Did this app post the message (rather than a person answering in the thread)?

    The app posts with the user's OAuth token, so the author id matches a human
    and cannot be used. Slack marks app-authored messages with `bot_id`, which
    covers the case body, the extra instructions and the attached APK. Known
    timestamps from `own_ts` cover older messages where that flag is missing.
    """
    if message.get('bot_id'):
        return True
    ts = message.get('ts')
    if ts in own or ts == record['ts']:
        return True
    # A message that carries one of our uploads is ours as well: Slack attaches
    # the file to a message posted with the user's own token.
    files = {f.get('id') for f in (message.get('files') or []) if f.get('id')}
    return bool(files & _own_file_ids(record))


async def _replies_from_channel(user_token, channel, record, wanted: set[str]):
    """Find our case in the channel when its recorded thread no longer exists.

    Returns `(replies, gone, root_ts)`, where `root_ts` is the message found. A message is accepted only if it is one we posted
    (a known timestamp, `bot_id`, or an upload of ours): deleting a stranger's
    message because it happened to be nearby would be worse than leaving ours.
    """
    known = _own_message_ts(record)
    known.discard('')
    try:
        candidates = await channel_messages_with_replies(user_token, channel)
    except (httpx.HTTPError, RuntimeError):
        return [], True, None
    for message in candidates:
        ts = message.get('ts')
        if ts not in wanted and ts not in known:
            continue
        if not _is_ours(record, message, known):
            continue
        try:
            replies = await list_thread_replies(user_token, channel, ts)
        except (httpx.HTTPError, RuntimeError):
            replies = [message]
        if not any(m.get('ts') == ts for m in replies):
            replies.insert(0, message)
        return replies, False, ts
    return [], True, None


async def delete_send(user_token, send_id, user_id=storage.LOCAL_USER_ID):
    """Delete a send's thread from Slack, then forget it locally.

    Everything is checked first: if anyone other than the app wrote in the
    thread, nothing is deleted at all. A partially deleted thread is worse than
    an untouched one, because the local history would no longer describe Slack.
    """
    record = read_send(send_id, user_id)
    channel = record['channel']
    thread_ts = record['thread_ts'] or record['ts']
    own = _own_message_ts(record)
    own.add(record['ts'])

    try:
        replies = await list_thread_replies(user_token, channel, thread_ts)
        gone_in_slack = False
    except (httpx.HTTPError, RuntimeError):
        # The thread start is gone (deleted by hand, or it was never ours). The
        # case body may still be there as its own root message, so look it up
        # before claiming there is nothing to delete.
        body_ts = posted_ts(record)
        replies = []
        gone_in_slack = True
        if body_ts and body_ts != thread_ts:
            try:
                replies = await list_thread_replies(user_token, channel, body_ts)
                gone_in_slack = False
            except (httpx.HTTPError, RuntimeError):
                replies = []
        if gone_in_slack:
            # Neither timestamp resolves. The body may still exist as a root
            # message whose thread we read, so look for it in the channel before
            # deciding there is nothing to delete. When it is found there, that
            # message *is* the start of the thread we delete.
            replies, gone_in_slack, found_root = await _replies_from_channel(
                user_token, channel, record, {thread_ts, body_ts})
            if found_root:
                thread_ts = found_root

    people = [m for m in replies if not _is_ours(record, m, own)]
    if people:
        raise ThreadHasPeopleReplies(len(people))

    if gone_in_slack:
        forget_send(send_id, user_id)
        return {'ok': True, 'deleted_messages': 0, 'send_id': send_id, 'already_gone': True}

    # Ours only: the parent plus anything the app posted in the thread
    # (instructions, APK upload notice, case picture). Newest first, parent last.
    # When the thread start is already gone, `replies` is the case body's own
    # thread, so its first message is that body and gets deleted here.
    deleted = 0
    for message in sorted(replies, key=lambda m: m.get('ts') or '', reverse=True):
        if message.get('ts') == thread_ts:
            # The parent is deleted below, where a foreign parent can be caught.
            continue
        answer = await delete_message(user_token, channel, message['ts'])
        if answer.get('ok'):
            deleted += 1
            continue
        error = answer.get('error', 'unknown_error')
        if error == 'message_not_found':
            # Already deleted by hand; keep going with the rest of the thread.
            # Its timestamp may still be what the parent deletion below uses.
            if message.get('ts'):
                own.add(message['ts'])
            continue
        raise HTTPException(
            502,
            f"Slack не удалил сообщение {message['ts']}: "
            f"{error}. Тред остался в Slack.",
        )
    # `thread_ts` is the start of the thread we actually read: usually the
    # recorded one, or the body's root message when the recorded start was gone.
    if thread_ts == record['ts']:
        # Posted while recording the send, so it is ours by construction.
        own.add(thread_ts)
    answer = await delete_message(user_token, channel, thread_ts)
    if answer.get('ok'):
        deleted += 1
    else:
        error = answer.get('error', 'unknown_error')
        if error != 'message_not_found':
            raise HTTPException(
                502,
                f"Slack не удалил сообщение {thread_ts}: "
                f"{error}. Тред остался в Slack.",
            )
        if not _is_ours(record, {'ts': thread_ts}, own):
            # The thread start was never posted by the app, so this is a foreign
            # message. Keep the record: the case body we deleted is now gone, so
            # deleting the row would hide where the case really lived.
            raise ThreadNotOursToDelete()

    forget_send(send_id, user_id)
    return {'ok': True, 'deleted_messages': deleted, 'send_id': send_id}


def forget_send(send_id, user_id=storage.LOCAL_USER_ID):
    """Drop the local record; cascades remove replies and case links."""
    with storage.connection() as db:
        db.execute('DELETE FROM slack_sends WHERE id=? AND owner_user_id=?', (send_id, user_id))


def attach_history(db, cases):
    """One database query for a set; one message may belong to several cases."""
    by_id = {case['id']: case for case in cases}
    for case in cases:
        case['slack_sends'] = []
    if not by_id:
        return
    placeholders = ','.join('?' for _ in by_id)
    rows = db.execute(f'''SELECT link.case_id, sends.* FROM slack_send_cases link
        JOIN slack_sends sends ON sends.id=link.send_id
        WHERE link.case_id IN ({placeholders}) ORDER BY sends.id DESC''', tuple(by_id))
    for row in rows:
        record = dict(row)
        by_id[record.pop('case_id')]['slack_sends'].append(record)
