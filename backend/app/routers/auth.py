"""Signup, login and current-user endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.logging_config import get_logger
from app.models import User
from app.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = get_logger("auth")


def _issue(user: User) -> TokenResponse:
    token = create_access_token(subject=user.id, role=user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: DbSession) -> TokenResponse:
    email = payload.email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # The very first account becomes the administrator so the admin views are
    # reachable on a fresh install without a seeding step.
    is_first_user = db.scalar(select(User.id).limit(1)) is None
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role="admin" if is_first_user else "user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("auth.signup", user_id=user.id, email=email, role=user.role)
    return _issue(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        log.warning("auth.login_failed", email=email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )
    log.info("auth.login", user_id=user.id, email=email)
    return _issue(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
