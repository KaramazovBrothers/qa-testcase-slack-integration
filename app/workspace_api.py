"""One transactional Save operation for draft or existing QA work."""
import json
import sqlite3
from fastapi import APIRouter, HTTPException, Response
from pydantic import Field, field_validator, model_validator
from app import storage
from app.current_user import CurrentUserId
from app.case_accounts import apply_account
from app.local_api import Model, TaskInput, Settings, CaseUpdate, require_task, get_set, now, task_identity, REGIONS

router=APIRouter(prefix='/api/tasks',tags=['Local QA workspace'])


class TestAccount(Model):
    id: str = Field(min_length=1,max_length=100)
    name: str = Field(min_length=1,max_length=200)
    account_id: str = Field(default='',max_length=4000)
    login: str = Field(default='',max_length=4000)
    password: str = Field(default='',max_length=4000)
    kind: str = 'main'

    @field_validator('name','account_id','login','password')
    @classmethod
    def single_line(cls,value):
        if '\n' in value or '\r' in value:
            raise ValueError('Account fields must contain one line')
        return value

    @field_validator('kind')
    @classmethod
    def kind_value(cls,value):
        if value not in ('main','usd'):raise ValueError('Invalid account kind')
        return value


class AccountSave(Model):
    region: str
    test_accounts: list[TestAccount] = Field(default_factory=list,max_length=100)
    deleted_account_ids: list[str] = Field(default_factory=list,max_length=100)

    @field_validator('region')
    @classmethod
    def region_value(cls,value):
        if value not in REGIONS:raise ValueError('Invalid region')
        return value


def read_accounts(db,user_id,region):
    return [dict(r) for r in db.execute('SELECT * FROM test_accounts WHERE owner_user_id=? AND region=? ORDER BY rowid',(user_id,region))]


def save_accounts(db,user_id,region,accounts,deleted):
    ids=[a.id for a in accounts]
    if len(ids)!=len(set(ids)) or set(ids)&set(deleted):raise HTTPException(422,'Conflicting account IDs')
    aliases={}
    for account in accounts:
        other=db.execute('SELECT * FROM test_accounts WHERE id=?',(account.id,)).fetchone()
        if other and (other['owner_user_id']!=user_id or other['region']!=region):raise HTTPException(404,'Account not found')
        # Reusing identical manually entered credentials must not create duplicates.
        same=db.execute('SELECT id FROM test_accounts WHERE owner_user_id=? AND region=? AND account_id=? AND login=? AND password=?',
            (user_id,region,account.account_id,account.login,account.password)).fetchone()
        if not other and same:
            aliases[account.id]=same['id'];continue
        aliases[account.id]=account.id
        db.execute('''INSERT INTO test_accounts(id,owner_user_id,region,name,account_id,login,password,kind) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,account_id=excluded.account_id,
            login=excluded.login,password=excluded.password,kind=excluded.kind''',
            (account.id,user_id,region,account.name,account.account_id,account.login,account.password,account.kind))
    for account_id in deleted:
        old=db.execute('SELECT owner_user_id,region FROM test_accounts WHERE id=?',(account_id,)).fetchone()
        if old and tuple(old)!=(user_id,region):raise HTTPException(404,'Account not found')
        db.execute('DELETE FROM test_accounts WHERE id=? AND owner_user_id=? AND region=?',(account_id,user_id,region))
    return aliases


@router.get('/accounts')
def list_accounts(region: str, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    if region not in REGIONS:raise HTTPException(422,'Invalid region')
    with storage.connection() as db:return read_accounts(db,user_id,region)


@router.post('/accounts')
def store_accounts(payload: AccountSave,user_id: CurrentUserId = storage.LOCAL_USER_ID):
    with storage.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        aliases=save_accounts(db,user_id,payload.region,payload.test_accounts,payload.deleted_account_ids)
        return {'accounts':read_accounts(db,user_id,payload.region),'aliases':aliases}


class SavedCase(CaseUpdate):
    id: int | None = Field(default=None,gt=0)
    client_key: str = Field(min_length=1,max_length=100)
    title: str = Field(min_length=1,max_length=4000)
    text: str = Field(min_length=1,max_length=100000)


class WorkspaceSave(TaskInput):
    task_id: int | None = Field(default=None,gt=0)
    client_key: str = Field(min_length=1,max_length=100)
    settings: Settings
    deleted_account_ids: list[str] = Field(default_factory=list,max_length=100)
    set_id: int | None = Field(default=None,gt=0)
    generation_key: str | None = Field(default=None,max_length=100)
    cases: list[SavedCase] | None = Field(default=None,max_length=500)
    test_accounts: list[TestAccount] = Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def unique_keys(self):
        for values in ([a.id for a in self.test_accounts], [c.client_key for c in self.cases or []], [c.id for c in self.cases or [] if c.id]):
            if len(values)!=len(set(values)):raise ValueError('Duplicate record ID')
        if self.cases is not None and not (self.set_id or self.generation_key):
            raise ValueError('Generation key is required for new cases')
        return self


@router.post('/save')
def save_workspace(payload: WorkspaceSave, response: Response, user_id: CurrentUserId = storage.LOCAL_USER_ID):
    try:
        with storage.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = require_task(db,payload.task_id,user_id) if payload.task_id else db.execute(
                'SELECT * FROM tasks WHERE owner_user_id=? AND client_key=?',(user_id,payload.client_key)).fetchone()
            settings=payload.settings.model_dump()
            region=settings['fields'].get('region','TR')
            if existing and existing['region'] and existing['region']!=region:
                raise HTTPException(409,'A task has one region. Create a new task for another region.')
            jira_id,title=task_identity(db,payload,user_id,existing)
            stamp=now()
            if existing:
                task_id=existing['id']
                db.execute('UPDATE tasks SET jira_id=?,title=?,settings=?,region=?,updated_at=? WHERE id=?',
                           (jira_id,title,json.dumps(settings,ensure_ascii=False),region,stamp,task_id))
            else:
                task_id=db.execute('INSERT INTO tasks(owner_user_id,jira_id,title,settings,region,created_at,updated_at,client_key) VALUES(?,?,?,?,?,?,?,?)',
                    (user_id,jira_id,title,json.dumps(settings,ensure_ascii=False),region,stamp,stamp,payload.client_key)).lastrowid
                response.status_code=201
            aliases=save_accounts(db,user_id,region,payload.test_accounts,payload.deleted_account_ids)
            account_ids={a['id'] for a in read_accounts(db,user_id,region)}
            set_id=payload.set_id
            if set_id:
                row=db.execute('SELECT * FROM case_sets WHERE id=? AND task_id=?',(set_id,task_id)).fetchone()
                if row is None:raise HTTPException(404,'Set not found')
                if row['region']!=region:raise HTTPException(409,'Historical set belongs to another region')
            if payload.cases is not None:
                mentions=settings['mention_edits'].get(region,[])
                operation='payout' if settings['fields'].get('integration')=='payout' else 'deposit'
                if not set_id:
                    row=db.execute('SELECT id FROM case_sets WHERE task_id=?',(task_id,)).fetchone()
                    if row:set_id=row['id']
                    else:
                        set_id=db.execute('INSERT INTO case_sets(task_id,name,created_at,settings,region,operation,mention_users,generation_key) VALUES(?,?,?,?,?,?,?,?)',
                            (task_id,'Набор · '+stamp,stamp,json.dumps(settings,ensure_ascii=False),region,operation,json.dumps(mentions),payload.generation_key)).lastrowid
                db.execute('UPDATE case_sets SET settings=?,mention_users=?,operation=? WHERE id=?',
                    (json.dumps(settings,ensure_ascii=False),json.dumps(mentions),operation,set_id))
                # Free ordinal slots before updating/reordering surviving case IDs.
                db.execute('UPDATE test_cases SET position=position+10000 WHERE set_id=?',(set_id,))
                kept=[]
                for position,case in enumerate(payload.cases):
                    case=case.model_copy(update={"test_account_id":aliases.get(case.test_account_id,case.test_account_id)})
                    if case.test_account_id and case.test_account_id not in account_ids:
                        raise HTTPException(422,'Select an account from this task')
                    case_id=case.id
                    if case_id:
                        row=db.execute('SELECT id FROM test_cases WHERE id=? AND set_id=?',(case_id,set_id)).fetchone()
                        if row is None:raise HTTPException(404,'Case not found')
                    else:
                        row=db.execute('SELECT id FROM test_cases WHERE set_id=? AND client_key=?',(set_id,case.client_key)).fetchone()
                        if row:case_id=row['id']
                    text=apply_account(db,task_id,case.test_account_id,case.text)
                    values=(position,case.title,text,case.comment,case.request_text,case.status,case.qa_comment,json.dumps(case.bug_links),stamp,case.test_account_id,case.client_key)
                    if case_id:
                        db.execute('UPDATE test_cases SET position=?,title=?,text=?,comment=?,request_text=?,status=?,qa_comment=?,bug_links=?,updated_at=?,test_account_id=?,client_key=? WHERE id=?',(*values,case_id))
                    else:
                        case_id=db.execute('INSERT INTO test_cases(position,title,text,comment,request_text,status,qa_comment,bug_links,updated_at,test_account_id,client_key,set_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(*values,set_id)).lastrowid
                    kept.append(case_id)
                for old in db.execute('SELECT id FROM test_cases WHERE set_id=?',(set_id,)).fetchall():
                    if old['id'] not in kept:db.execute('DELETE FROM test_cases WHERE id=?',(old['id'],))
            result=storage.decode(require_task(db,task_id,user_id),'settings')
            result['test_accounts']=read_accounts(db,user_id,region)
            return {'task':result,'set':get_set(db,task_id,set_id,user_id) if set_id else None}
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409,'Conflicting Jira ID or record reference') from exc
