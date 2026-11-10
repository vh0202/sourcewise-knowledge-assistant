"""Sign-in, sign-out and the current user.

Sessions are opaque random tokens in an HttpOnly, SameSite=Strict cookie. The cookie is never
readable by page scripts and is not sent on cross-site requests, which is what protects the
state-changing endpoints against CSRF in this same-origin deployment.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, select

from .. import security
from ..db import utcnow
from ..models import AuthSession, User
from ..schemas import LoginRequest, SessionOut, UserOut
from .deps import SESSION_COOKIE, ContainerDep, CurrentUser, SessionDep, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(
    payload: LoginRequest, request: Request, response: Response, session: SessionDep, container: ContainerDep
) -> User:
    email = payload.email.strip().lower()
    client_host = request.client.host if request.client else "unknown"
    throttle_key = f"{client_host}:{email}"
    if container.throttle.is_blocked(throttle_key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed sign-in attempts. Try again in a few minutes."
        )

    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not security.verify_password(payload.password, user.password_hash):
        container.throttle.record_failure(throttle_key)
        # One message for both cases, so the response does not reveal which accounts exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    container.throttle.reset(throttle_key)

    now = utcnow()
    ttl = timedelta(hours=container.settings.session_ttl_hours)
    session.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    token = security.new_session_token()
    session.add(AuthSession(user_id=user.id, token_hash=security.hash_token(token), expires_at=now + ttl))
    session.commit()

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=container.settings.cookie_secure,
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, session: SessionDep) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == security.hash_token(token)))
        session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.get("/session", response_model=SessionOut)
def session_state(request: Request, session: SessionDep) -> SessionOut:
    """Who is signed in, if anyone. Lets the web app start up without provoking a 401."""
    try:
        return SessionOut(user=UserOut.model_validate(get_current_user(request, session)))
    except HTTPException:
        return SessionOut(user=None)
