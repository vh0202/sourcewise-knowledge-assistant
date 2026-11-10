"""FastAPI dependencies: the container, a database session, and the signed-in user.

Authorisation lives here and nowhere else: every route declares ``CurrentUser`` or
``AdminUser`` and the server enforces it, regardless of what the UI chooses to show.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..container import Container
from ..db import utcnow
from ..models import AuthSession, User
from ..security import hash_token

SESSION_COOKIE = "sourcewise_session"


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_session(container: Annotated[Container, Depends(get_container)]) -> Iterator[Session]:
    with container.session_factory() as session:
        yield session


def get_current_user(request: Request, session: Annotated[Session, Depends(get_session)]) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_session = session.execute(
            select(AuthSession).where(AuthSession.token_hash == hash_token(token))
        ).scalar_one_or_none()
        if auth_session is not None and auth_session.expires_at > utcnow():
            return auth_session.user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This action requires an administrator account.")
    return user


ContainerDep = Annotated[Container, Depends(get_container)]
SessionDep = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
