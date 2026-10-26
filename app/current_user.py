"""Server-owned identity boundary for future authentication integration.

Do not accept a user ID from request headers, query strings or JSON. Until login
is implemented, the local installation always acts as its original QA user.
"""
from typing import Annotated
from fastapi import Depends
from app.storage import LOCAL_USER_ID


def get_current_user_id() -> int:
    return LOCAL_USER_ID


CurrentUserId = Annotated[int, Depends(get_current_user_id)]
