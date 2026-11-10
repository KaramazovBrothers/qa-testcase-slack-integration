"""Server-owned identity boundary.

There are two ways to learn who is calling:

* `proxy` mode (`QAHELPER_ACCESS_MODE=proxy`): a trusted reverse proxy has
  already authenticated the person and passes the verified identity in the
  header named by `QAHELPER_IDENTITY_HEADER` (default `x-auth-request-email`).
  The header is never trusted in local mode, so a browser cannot forge it while
  the app runs on loopback.
* local mode (default): the installation acts as its original QA user.

Either way the user ID comes from the server-side `users` table; a request
never supplies it.
"""
import os
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app import storage
from app.local_access import access_mode

DEFAULT_IDENTITY_HEADER = 'x-auth-request-email'


def identity_header() -> str:
    return (os.getenv('QAHELPER_IDENTITY_HEADER') or DEFAULT_IDENTITY_HEADER).strip().lower()


def resolve_user_id(request: Request | None) -> int:
    """Map the authenticated person to a `users` row, creating it on first sight."""
    if access_mode() != 'proxy':
        return storage.LOCAL_USER_ID
    raw = request.headers.get(identity_header(), '') if request is not None else ''
    subject = raw.strip()
    if not subject:
        raise HTTPException(status_code=401, detail='Not authenticated')
    user_id = storage.ensure_user('sso', subject, subject)
    if user_id is None:
        raise HTTPException(status_code=403, detail='No workspace account for this identity')
    return user_id


def get_current_user_id(request: Request) -> int:
    return resolve_user_id(request)


CurrentUserId = Annotated[int, Depends(get_current_user_id)]
