"""Shared fixtures. Every test runs against a temporary database; nothing touches ``data/``."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sourcewise.config import PROJECT_ROOT, Settings
from sourcewise.container import Container, build_container
from sourcewise.main import create_app
from sourcewise.seed import DEMO_USERS, _seed_users, seed

ADMIN = next(user for user in DEMO_USERS if user["role"] == "admin")
MEMBER = next(user for user in DEMO_USERS if user["role"] == "member")


def make_settings(data_dir: Path, **overrides) -> Settings:
    """Explicit settings so that the tests do not depend on the developer's environment or .env."""
    values = {
        "data_dir": data_dir,
        "frontend_dist": data_dir / "no-frontend",
        "corpus_dir": PROJECT_ROOT / "corpus",
        "engine": "offline",
        "retriever": "auto",
        "anthropic_api_key": None,
        "stream_delay_ms": 0,
        "top_k": 6,
        "min_coverage": 0.55,
        "min_evidence": 0.5,
        "chunk_max_chars": 700,
        "chunk_overlap_chars": 150,
        "fallback_to_offline": True,
        "show_demo_accounts": True,
        "max_upload_mb": 10,
        "cookie_secure": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path / "data")


@pytest.fixture
def container(settings: Settings) -> Iterator[Container]:
    """An empty knowledge base with the two demo accounts."""
    built = build_container(settings)
    with built.session_factory() as session:
        _seed_users(session)
    yield built
    built.close()


@pytest.fixture(scope="session")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Container]:
    """The full sample corpus, ingested once per test session. Treat the knowledge base as read-only."""
    built = build_container(make_settings(tmp_path_factory.mktemp("seeded") / "data"))
    summary = seed(built, with_activity=False)
    assert not summary["problems"], summary["problems"]
    yield built
    built.close()


def _client_for(container: Container) -> TestClient:
    return TestClient(create_app(container.settings, container=container))


def sign_in(client: TestClient, user: dict[str, str]) -> TestClient:
    response = client.post("/api/auth/login", json={"email": user["email"], "password": user["password"]})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def anonymous(container: Container) -> TestClient:
    return _client_for(container)


@pytest.fixture
def admin(container: Container) -> TestClient:
    return sign_in(_client_for(container), ADMIN)


@pytest.fixture
def member(container: Container) -> TestClient:
    return sign_in(_client_for(container), MEMBER)


@pytest.fixture(scope="session")
def seeded_admin(seeded: Container) -> TestClient:
    return sign_in(_client_for(seeded), ADMIN)


@pytest.fixture(scope="session")
def seeded_member(seeded: Container) -> TestClient:
    return sign_in(_client_for(seeded), MEMBER)


@pytest.fixture
def client_factory() -> Callable[[Container], TestClient]:
    return _client_for


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse a server-sent event stream into ``(event, data)`` pairs."""
    import json

    events = []
    for block in body.strip().split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name is not None:
            events.append((name, data))
    return events
