"""Authentication, sessions and server-side permission checks."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sourcewise import security
from sourcewise.api.deps import SESSION_COOKIE
from sourcewise.container import Container
from sourcewise.db import utcnow
from sourcewise.models import AuthSession, Collection, User

from .conftest import ADMIN, MEMBER, sign_in


# -- passwords and tokens ----------------------------------------------------------------------
def test_passwords_are_hashed_with_a_salted_slow_function() -> None:
    first, second = security.hash_password("correct horse"), security.hash_password("correct horse")
    assert first != second  # a fresh salt every time
    assert first.startswith("scrypt$") and "correct horse" not in first
    assert security.verify_password("correct horse", first)
    assert not security.verify_password("wrong horse", first)
    assert not security.verify_password("correct horse", "not-a-valid-hash")
    assert not security.verify_password("correct horse", "bcrypt$1$2$3$4$5")


def test_seeded_users_store_only_hashes(container: Container) -> None:
    with container.session_factory() as session:
        users = session.execute(select(User)).scalars().all()
    assert {user.email for user in users} == {ADMIN["email"], MEMBER["email"]}
    for user in users:
        assert user.password_hash.startswith("scrypt$")
        assert ADMIN["password"] not in user.password_hash and MEMBER["password"] not in user.password_hash


def test_login_throttle_blocks_after_repeated_failures_and_resets_on_success() -> None:
    throttle = security.LoginThrottle(max_failures=3, window_seconds=60)
    for _ in range(3):
        assert not throttle.is_blocked("key")
        throttle.record_failure("key")
    assert throttle.is_blocked("key")
    assert not throttle.is_blocked("someone-else")
    throttle.reset("key")
    assert not throttle.is_blocked("key")


# -- sign-in -----------------------------------------------------------------------------------
def test_login_sets_a_hardened_session_cookie_and_returns_the_user(anonymous: TestClient) -> None:
    response = anonymous.post("/api/auth/login", json={"email": "ADMIN@example.com ", "password": ADMIN["password"]})
    assert response.status_code == 200
    assert response.json() == {"id": response.json()["id"], "email": ADMIN["email"], "name": ADMIN["name"], "role": "admin"}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie and "samesite=strict" in cookie.lower() and "Path=/" in cookie
    assert anonymous.get("/api/auth/me").json()["email"] == ADMIN["email"]


def test_only_a_hash_of_the_session_token_is_stored(anonymous: TestClient, container: Container) -> None:
    sign_in(anonymous, MEMBER)
    token = anonymous.cookies.get(SESSION_COOKIE)
    with container.session_factory() as session:
        stored = session.execute(select(AuthSession)).scalars().one()
    assert stored.token_hash == security.hash_token(token) != token


@pytest.mark.parametrize(
    "credentials",
    [
        {"email": ADMIN["email"], "password": "wrong-password"},
        {"email": "nobody@example.com", "password": ADMIN["password"]},
    ],
)
def test_wrong_credentials_get_the_same_generic_error(anonymous: TestClient, credentials: dict) -> None:
    response = anonymous.post("/api/auth/login", json=credentials)
    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password."}
    assert "set-cookie" not in response.headers


def test_malformed_login_is_rejected(anonymous: TestClient) -> None:
    assert anonymous.post("/api/auth/login", json={"email": ADMIN["email"]}).status_code == 422
    assert anonymous.post("/api/auth/login", json={"email": "", "password": ""}).status_code == 422


def test_repeated_failed_logins_are_throttled(anonymous: TestClient) -> None:
    attempt = {"email": MEMBER["email"], "password": "guess"}
    statuses = [anonymous.post("/api/auth/login", json=attempt).status_code for _ in range(9)]
    assert statuses[:8] == [401] * 8
    assert statuses[8] == 429
    # Even the right password is refused while the block is in place.
    assert anonymous.post("/api/auth/login", json={"email": MEMBER["email"], "password": MEMBER["password"]}).status_code == 429


def test_logout_invalidates_the_session_on_the_server(member: TestClient, container: Container) -> None:
    token = member.cookies.get(SESSION_COOKIE)
    assert member.post("/api/auth/logout").status_code == 204
    assert member.get("/api/auth/me").status_code == 401
    # Replaying the old cookie does not work either: the session row is gone.
    member.cookies.set(SESSION_COOKIE, token)
    assert member.get("/api/auth/me").status_code == 401
    with container.session_factory() as session:
        assert session.execute(select(AuthSession)).scalars().all() == []


def test_expired_and_forged_sessions_are_rejected(member: TestClient, container: Container) -> None:
    with container.session_factory() as session:
        stored = session.execute(select(AuthSession)).scalars().one()
        stored.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert member.get("/api/auth/me").status_code == 401

    member.cookies.set(SESSION_COOKIE, "forged-token")
    assert member.get("/api/auth/me").status_code == 401


# -- permissions -------------------------------------------------------------------------------
PROTECTED = [
    ("GET", "/api/auth/me"),
    ("GET", "/api/collections"),
    ("POST", "/api/collections"),
    ("GET", "/api/documents"),
    ("POST", "/api/documents"),
    ("GET", "/api/documents/1"),
    ("GET", "/api/documents/1/chunks"),
    ("POST", "/api/documents/1/reindex"),
    ("DELETE", "/api/documents/1"),
    ("GET", "/api/conversations"),
    ("POST", "/api/conversations"),
    ("GET", "/api/conversations/1"),
    ("POST", "/api/conversations/1/messages"),
    ("POST", "/api/messages/1/feedback"),
    ("GET", "/api/suggestions"),
    ("GET", "/api/insights"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_every_data_endpoint_requires_a_session(anonymous: TestClient, method: str, path: str) -> None:
    response = anonymous.request(method, path)
    assert response.status_code == 401, f"{method} {path} is reachable without signing in"
    assert response.json() == {"detail": "Sign in to continue."}


def test_public_endpoints_need_no_session(anonymous: TestClient) -> None:
    assert anonymous.get("/api/health").json() == {"status": "ok"}
    assert anonymous.get("/api/meta").status_code == 200


def test_session_endpoint_reports_who_is_signed_in_without_erroring(anonymous: TestClient) -> None:
    assert anonymous.get("/api/auth/session").json() == {"user": None}
    sign_in(anonymous, MEMBER)
    signed_in = anonymous.get("/api/auth/session").json()["user"]
    assert (signed_in["email"], signed_in["role"]) == (MEMBER["email"], "member")
    assert set(signed_in) == {"id", "email", "name", "role"}  # never the password hash
    anonymous.post("/api/auth/logout")
    assert anonymous.get("/api/auth/session").json() == {"user": None}


ADMIN_ONLY = [
    ("POST", "/api/collections", {"json": {"name": "New", "description": ""}}),
    ("PATCH", "/api/collections/1", {"json": {"name": "Renamed", "description": ""}}),
    ("DELETE", "/api/collections/1", {}),
    ("GET", "/api/documents", {}),
    ("POST", "/api/documents", {"files": {"file": ("a.txt", b"Some text.", "text/plain")}, "data": {"collection_id": "1"}}),
    ("GET", "/api/documents/1", {}),
    ("GET", "/api/documents/1/chunks", {}),
    ("POST", "/api/documents/1/reindex", {}),
    ("DELETE", "/api/documents/1", {}),
    ("GET", "/api/insights", {}),
]


@pytest.mark.parametrize(("method", "path", "kwargs"), ADMIN_ONLY)
def test_members_cannot_use_admin_endpoints(member: TestClient, container: Container, method: str, path: str, kwargs: dict) -> None:
    with container.session_factory() as session:
        session.add(Collection(name="Existing", description="", starter_questions=[]))
        session.commit()
    response = member.request(method, path, **kwargs)
    assert response.status_code == 403, f"{method} {path} is open to members"
    assert response.json() == {"detail": "This action requires an administrator account."}
    # ... and nothing was changed.
    with container.session_factory() as session:
        assert [c.name for c in session.execute(select(Collection)).scalars()] == ["Existing"]


def test_members_can_use_the_chat_side(member: TestClient) -> None:
    assert member.get("/api/collections").status_code == 200
    assert member.get("/api/suggestions").status_code == 200
    assert member.get("/api/conversations").json() == []
    assert member.post("/api/conversations", json={}).status_code == 201


def test_conversations_are_private_to_their_owner(admin: TestClient, member: TestClient) -> None:
    conversation = member.post("/api/conversations", json={"title": "Private"}).json()
    answer = member.post(
        f"/api/conversations/{conversation['id']}/messages", json={"content": "hello", "stream": False}
    ).json()

    path = f"/api/conversations/{conversation['id']}"
    # An admin is still just another user as far as someone else's conversation is concerned.
    assert admin.get(path).status_code == 404
    assert admin.patch(path, json={"title": "Hijacked"}).status_code == 404
    assert admin.delete(path).status_code == 404
    assert admin.post(f"{path}/messages", json={"content": "sneaky", "stream": False}).status_code == 404
    assert admin.post(f"/api/messages/{answer['id']}/feedback", json={"value": 1}).status_code == 404
    assert admin.get("/api/conversations").json() == []

    owned = member.get(path).json()
    assert owned["title"] == "Private" and len(owned["messages"]) == 2
    assert owned["messages"][1]["feedback"] is None
