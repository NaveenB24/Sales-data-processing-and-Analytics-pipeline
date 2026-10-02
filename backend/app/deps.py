"""Shared FastAPI dependencies: DB session, current user, admin guard, ownership."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Job, User
from app.ratelimit import TokenBucketLimiter
from app.security import TokenError, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)

upload_limiter = TokenBucketLimiter(
    capacity=settings.upload_rate_limit, window_seconds=float(settings.upload_rate_window_seconds)
)

DbSession = Annotated[Session, Depends(get_db)]

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise _CREDENTIALS_ERROR
    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError:
        raise _CREDENTIALS_ERROR from None
    user_id = payload.get("sub")
    if not user_id:
        raise _CREDENTIALS_ERROR
    user = db.get(User, user_id)
    if user is None:
        raise _CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def get_owned_job(job_id: str, db: Session, user: User) -> Job:
    """Fetch a job the caller may see. Non-owners get 404 to avoid id enumeration."""
    job = db.get(Job, job_id)
    if job is None or (job.user_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job
