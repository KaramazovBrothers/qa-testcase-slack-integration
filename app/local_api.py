"""Owner-scoped local QA workspace API; the generator remains browser-owned."""
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator, model_validator
from app import storage, slack_history
from app.current_user import CurrentUserId

router = APIRouter(prefix='/api/tasks', tags=['Local QA workspace'])
Status = Literal['Not tested', 'Passed', 'Failed', 'Blocked', 'Skipped']
REGIONS = {'TR','AZ','CL','CA','GT','KZ','BO','UZ','IN','KG','BD','MX','EC','HN','TJ','NG','KE','CG','RU'}
SELECTS = {'integration': {'HPP','H2H','payout'}, 'license': {'pinco','com','zazino'},
           'region': REGIONS, 'wallet': {'standard','apple','google'}, 'amountChange': {'yes','no'},
           'cardNetwork': {'visa','mastercard','both'}, 'googleMethodMode': {'separate','shared'},
           'qrScanner': {'camera','app','both'}, 'qrMobile': {'button','download'}}
CHECKS = {'returnToCashier','receipt','oneClick','qr','timer','cancel'}
AMOUNTS = {'amount','payoutAmount','payoutFeeAmount','overRequest','overPaid','underRequest','underPaid',
           'usdAmount','usdUnderRequest','usdUnderPaid','usdOverRequest','usdOverPaid'}
TEXTS = {'site','method','nativeMethod','account','login','password','usdAccount','usdLogin','usdPassword'}


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)


class TaskInput(Model):
    jira_id: str = Field(min_length=3, max_length=80)
    title: str = Field(min_length=1, max_length=300)

    @field_validator('jira_id')
    @classmethod
    def jira(cls, value):
        value = value.strip().upper()
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*-[1-9][0-9]*', value):
            raise ValueError('Expected Jira ID such as QA-123')
        return value

    @field_validator('title')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Title cannot be blank')
        return value.strip()


class Settings(Model):
    fields: dict[str, StrictStr | StrictBool] = Field(default_factory=dict, max_length=100)
    language: Literal['ru','en','uk'] = 'ru'
    payout_fee_manual: bool = False
    mention_edits: dict[str, list[str]] = Field(default_factory=dict, max_length=19)

    @field_validator('fields')
    @classmethod
    def validate_fields(cls, values):
        for key, value in values.items():
            if key in CHECKS:
                if not isinstance(value, bool):
                    raise ValueError(f'{key} must be boolean')
            elif key in SELECTS or key in AMOUNTS or key in TEXTS:
                if not isinstance(value, str) or len(value) > 4000:
                    raise ValueError(f'Invalid {key}')
                if key in SELECTS and value not in SELECTS[key]:
                    raise ValueError(f'Invalid option for {key}')
                if key in AMOUNTS and not re.fullmatch(r'[0-9]{0,6}', value):
                    raise ValueError(f'Invalid amount for {key}')
            else:
                raise ValueError(f'Unknown generator field: {key}')
        return values

    @field_validator('mention_edits')
    @classmethod
    def mentions(cls, values):
        from app.mentions import normalize_mentions
        for region, names in values.items():
            if region not in REGIONS or len(names) > 100:
                raise ValueError('Invalid region mentions')
            normalize_mentions([name for name in names if name.strip()])
        return values


class CaseInput(Model):
    title: str = Field(min_length=1, max_length=4000)
    text: str = Field(min_length=1, max_length=100000)
    comment: str = Field(default='', max_length=20000)
    request_text: str | None = Field(default=None, max_length=2000)

    @field_validator('title', 'text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Case title and text cannot be blank')
        return value


class SetInput(Model):
    name: str = Field(min_length=1, max_length=200)
    settings: Settings
    region: str
    operation: Literal['deposit','payout'] = 'deposit'
    mention_users: list[str] | None = Field(default=None, max_length=100)
    cases: list[CaseInput] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def validate_context(self):
        from app.mentions import normalize_mentions
        if self.region not in REGIONS:
            raise ValueError('Invalid region')
        if not self.name.strip():
            raise ValueError('Set name cannot be blank')
        if self.mention_users is not None:
            self.mention_users = normalize_mentions(self.mention_users)
        fields = self.settings.fields
        if fields.get('region', self.region) != self.region:
            raise ValueError('Region must match generator settings')
        if 'integration' in fields and self.operation != ('payout' if fields['integration'] == 'payout' else 'deposit'):
            raise ValueError('Operation must match generator settings')
        return self


class CaseUpdate(CaseInput):
    title: str = Field(default='', min_length=1, max_length=4000)
    text: str = Field(default='', min_length=1, max_length=100000)
    status: Status = 'Not tested'
    qa_comment: str = Field(default='', max_length=20000)
    bug_links: list[str] = Field(default_factory=list, max_length=50)

    @field_validator('bug_links')
    @classmethod
    def links(cls, values):
        for value in values:
            url = urlsplit(value)
            if len(value) > 2048 or url.scheme not in ('https','http') or not url.hostname or url.username or url.password:
                raise ValueError('Bug links must be HTTP(S) URLs without credentials')
        return list(dict.fromkeys(values))


def now():
    return datetime.now(timezone.utc).isoformat()


def require(db, table, record_id, clause='', params=()):
    row = db.execute(f'SELECT * FROM {table} WHERE id=? {clause}', (record_id, *params)).fetchone()
    if row is None:
        raise HTTPException(404, 'Not found')
    return row


def touch(db, task_id):
    db.execute('UPDATE tasks SET updated_at=? WHERE id=?', (now(), task_id))


def require_task(db, task_id, user_id):
    return require(db, 'tasks', task_id, 'AND owner_user_id=?', (user_id,))


def get_set(db, task_id, set_id, user_id=storage.LOCAL_USER_ID):
    require_task(db, task_id, user_id)
    row = require(db, 'case_sets', set_id, 'AND task_id=?', (task_id,))
    result = storage.decode(row, 'settings', 'mention_users')
    result['cases'] = [storage.decode(r, 'bug_links') for r in db.execute(
        'SELECT * FROM test_cases WHERE set_id=? ORDER BY position', (set_id,))]
    slack_history.attach_history(db, result['cases'])
    result['counts'] = {s: sum(c['status'] == s for c in result['cases']) for s in ('Not tested','Passed','Failed','Blocked','Skipped')}
    return result


@router.get('')
def list_tasks(q: str = Query(default='', max_length=80), user_id: CurrentUserId = storage.LOCAL_USER_ID):
    with storage.connection() as db:
        return [dict(r) for r in db.execute('SELECT id,jira_id,title,created_at,updated_at FROM tasks WHERE owner_user_id=? AND instr(upper(jira_id),upper(?))>0 ORDER BY updated_at DESC,id DESC', (user_id,q.strip()))]


@router.post('', status_code=201)
def create_task(payload: TaskInput, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    try:
        with storage.connection() as db:
            stamp = now()
            cursor = db.execute('INSERT INTO tasks(owner_user_id,jira_id,title,created_at,updated_at) VALUES(?,?,?,?,?)', (user_id,payload.jira_id,payload.title,stamp,stamp))
            return storage.decode(require_task(db,cursor.lastrowid,user_id),'settings')
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, 'Jira ID already exists') from exc


@router.get('/{task_id}')
def read_task(task_id: int, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    with storage.connection() as db:
        return storage.decode(require_task(db,task_id,user_id),'settings')


@router.put('/{task_id}')
def update_task(task_id: int, payload: TaskInput, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    try:
        with storage.connection() as db:
            require_task(db,task_id,user_id)
            db.execute('UPDATE tasks SET jira_id=?,title=?,updated_at=? WHERE id=?', (payload.jira_id,payload.title,now(),task_id))
            return storage.decode(require_task(db,task_id,user_id),'settings')
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, 'Jira ID already exists') from exc


@router.delete('/{task_id}', status_code=204)
def delete_task(task_id: int, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    with storage.connection() as db:
        require_task(db,task_id,user_id)
        db.execute('DELETE FROM tasks WHERE id=?',(task_id,))
    return Response(status_code=204)


@router.get('/{task_id}/settings')
def read_settings(task_id: int, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    with storage.connection() as db:
        return json.loads(require_task(db,task_id,user_id)['settings'])


@router.put('/{task_id}/settings')
def save_settings(task_id: int, payload: Settings, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    with storage.connection() as db:
        require_task(db,task_id,user_id)
        db.execute('UPDATE tasks SET settings=?,updated_at=? WHERE id=?', (payload.model_dump_json(),now(),task_id))
    return payload


@router.get('/{task_id}/sets')
def list_sets(task_id: int, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    with storage.connection() as db:
        require_task(db,task_id,user_id)
        return [dict(r) for r in db.execute('SELECT id,name,created_at,(SELECT count(*) FROM test_cases WHERE set_id=case_sets.id) AS case_count FROM case_sets WHERE task_id=? ORDER BY id DESC',(task_id,))]


@router.post('/{task_id}/sets', status_code=201)
def save_set(task_id: int, payload: SetInput, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    with storage.connection() as db:
        require_task(db,task_id,user_id)
        stamp = now()
        cursor = db.execute('INSERT INTO case_sets(task_id,name,created_at,settings,region,operation,mention_users) VALUES(?,?,?,?,?,?,?)',
                            (task_id,payload.name.strip(),stamp,payload.settings.model_dump_json(),payload.region,payload.operation,json.dumps(payload.mention_users)))
        set_id = cursor.lastrowid
        db.executemany('INSERT INTO test_cases(set_id,position,title,text,comment,request_text,updated_at) VALUES(?,?,?,?,?,?,?)',
                       [(set_id,i,c.title,c.text,c.comment,c.request_text,stamp) for i,c in enumerate(payload.cases)])
        db.execute('UPDATE tasks SET settings=?,updated_at=? WHERE id=?', (payload.settings.model_dump_json(),stamp,task_id))
        return get_set(db,task_id,set_id,user_id)


@router.get('/{task_id}/sets/{set_id}')
def read_set(task_id: int, set_id: int, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    with storage.connection() as db:
        return get_set(db,task_id,set_id,user_id)


@router.patch('/{task_id}/sets/{set_id}/cases/{case_id}')
def update_case(task_id: int, set_id: int, case_id: int, payload: CaseUpdate, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    # Only explicitly provided fields are updated; defaults are never written.
    with storage.connection() as db:
        require_task(db,task_id,user_id)
        require(db,'case_sets',set_id,'AND task_id=?',(task_id,))
        require(db,'test_cases',case_id,'AND set_id=?',(set_id,))
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            db.execute(f'UPDATE test_cases SET {key}=? WHERE id=?', (json.dumps(value) if key=='bug_links' else value, case_id))
        db.execute('UPDATE test_cases SET updated_at=? WHERE id=?', (now(),case_id))
        touch(db,task_id)
        return storage.decode(require(db,'test_cases',case_id),'bug_links')


@router.post('/{task_id}/sets/{set_id}/cases/{case_id}/slack-sends/{send_id}/permalink')
async def retry_slack_permalink(task_id: int, set_id: int, case_id: int, send_id: int, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    # Local import avoids a router/main import cycle; the existing User OAuth
    # session remains the sole source of credentials.
    from app.main import require_slack_token

    with storage.connection() as db:
        require_task(db,task_id,user_id)
        require(db, 'case_sets', set_id, 'AND task_id=?', (task_id,))
        require(db, 'test_cases', case_id, 'AND set_id=?', (set_id,))
        if not db.execute('SELECT 1 FROM slack_send_cases WHERE send_id=? AND case_id=?', (send_id, case_id)).fetchone():
            raise HTTPException(404, 'Slack send not found for this case')
    return await slack_history.resolve_permalink(require_slack_token(user_id), send_id, user_id)
