"""Persist acknowledged Slack messages before attempting permalink resolution."""
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from app import storage
from app.slack_client import get_permalink, list_thread_replies, delete_message


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
    """Remember another message the app posted in this thread (instructions)."""
    if not isinstance(ts, str) or not ts:
        return
    with storage.connection() as db:
        row = db.execute('SELECT own_ts FROM slack_sends WHERE id=? AND owner_user_id=?', (send_id, user_id)).fetchone()
        if row is None:
            return
        own = json.loads(row['own_ts'] or '[]')
        if ts not in own:
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
    except Exception:
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


async def delete_send(user_token, send_id, user_id=storage.LOCAL_USER_ID):
    """Delete a send's thread from Slack, then forget it locally.

    Everything is checked first: if anyone other than the app wrote in the
    thread, nothing is deleted at all. A partially deleted thread is worse than
    an untouched one, because the local history would no longer describe Slack.
    """
    record = read_send(send_id, user_id)
    channel = record['channel']
    thread_ts = record['thread_ts'] or record['ts']
    own = set(json.loads(record['own_ts'] or '[]'))
    own.add(record['ts'])

    try:
        replies = await list_thread_replies(user_token, channel, thread_ts)
    except Exception:
        # The thread is already gone in Slack (deleted by hand, or pruned).
        # There is nothing to delete there, so only the local record is removed.
        replies = []
        gone_in_slack = True
    else:
        gone_in_slack = False

    people = [m for m in replies if m.get('ts') not in own]
    if people:
        raise ThreadHasPeopleReplies(len(people))

    if gone_in_slack:
        forget_send(send_id, user_id)
        return {'ok': True, 'deleted_messages': 0, 'send_id': send_id, 'already_gone': True}

    # Ours only: the parent plus anything the app posted in the thread
    # (instructions, APK upload notice). Newest first, parent last.
    for message in sorted(replies, key=lambda m: m.get('ts') or '', reverse=True):
        answer = await delete_message(user_token, channel, message['ts'])
        if not answer.get('ok'):
            error = answer.get('error', 'unknown_error')
            if error == 'message_not_found':
                # Already deleted by hand; keep going with the rest of the thread.
                continue
            raise HTTPException(
                502,
                f"Slack не удалил сообщение {message['ts']}: "
                f"{error}. Тред остался в Slack.",
            )
    answer = await delete_message(user_token, channel, record['ts'])
    if not answer.get('ok'):
        error = answer.get('error', 'unknown_error')
        if error != 'message_not_found':
            raise HTTPException(
                502,
                f"Slack не удалил сообщение {record['ts']}: "
                f"{error}. Тред остался в Slack.",
            )

    forget_send(send_id, user_id)
    return {'ok': True, 'deleted_messages': len(replies) + 1, 'send_id': send_id}


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
