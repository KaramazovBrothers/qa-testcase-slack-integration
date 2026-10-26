"""Persist acknowledged Slack messages before attempting permalink resolution."""
from datetime import datetime, timezone

from fastapi import HTTPException
from app import storage
from app.slack_client import get_permalink


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


def record_send(case_ids, response, user_id=storage.LOCAL_USER_ID):
    # ts must remain a string: float conversion loses Slack timestamp precision.
    channel, ts = response.get('channel'), response.get('ts')
    if not isinstance(channel, str) or not channel or not isinstance(ts, str) or not ts:
        raise HTTPException(502, 'Message posted, but Slack returned no channel/ts. Check Slack before sending again.')
    with storage.connection() as db:
        cursor = db.execute('INSERT INTO slack_sends(owner_user_id,channel,ts,sent_at) VALUES(?,?,?,?)', (user_id, channel, ts, now()))
        send_id = cursor.lastrowid
        db.executemany('INSERT INTO slack_send_cases(send_id,case_id) VALUES(?,?)',
                       [(send_id, case_id) for case_id in set(case_ids)])
    return send_id


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
