"""Replace only credential header fields; preserve edited test steps verbatim."""
import re
from fastapi import HTTPException


def apply_account(db, task_id, account_id, text):
    if account_id is None:
        return text
    account=db.execute('''SELECT a.* FROM test_accounts a JOIN tasks t ON t.owner_user_id=a.owner_user_id
        AND t.region=a.region WHERE a.id=? AND t.id=?''',(account_id,task_id)).fetchone()
    if account is None:
        raise HTTPException(422,'Test account does not belong to this owner and region')
    lines=text.splitlines()
    labels=[(r'(?:AccountID|ID акаунта|ID аккаунта):','account_id','AccountID:'),
            (r'(?:login|логін|Логин):','login','login:'),
            (r'(?:Password|Пароль):','password','Password:')]
    # Credential headers are in the first block, never in the scenario steps.
    boundary=next((i for i,line in enumerate(lines) if not line.strip()),len(lines))
    missing=[]
    for pattern,key,fallback in labels:
        value=account[key]
        for i in range(boundary):
            match=re.match('^('+pattern+r')\s*',lines[i],re.IGNORECASE)
            if match:
                lines[i]=match.group(1)+' '+value
                break
        else:
            missing.append(fallback+' '+value)
    return '\n'.join(missing+lines)
