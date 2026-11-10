"""Configuration: defaults, environment variables and the documented example file."""

from __future__ import annotations

import pytest

from sourcewise.config import PROJECT_ROOT, Settings

EXAMPLE = PROJECT_ROOT / ".env.example"
# Paths that only matter to someone restructuring the repository; not worth documenting for users.
UNDOCUMENTED = {"frontend_dist", "corpus_dir"}


def variable_name(field: str) -> str:
    return "ANTHROPIC_API_KEY" if field == "anthropic_api_key" else f"SOURCEWISE_{field.upper()}"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The developer's own environment must not leak into these tests."""
    for field in Settings.model_fields:
        monkeypatch.delenv(variable_name(field), raising=False)


def test_defaults_run_offline_on_port_8102() -> None:
    settings = Settings(_env_file=None)
    assert (settings.host, settings.port) == ("127.0.0.1", 8102)
    assert settings.anthropic_api_key is None and settings.resolved_engine == "offline"
    assert settings.database_url.endswith("/data/sourcewise.db")
    assert settings.upload_dir == settings.data_dir / "uploads"


def test_the_example_file_is_valid_and_states_the_real_defaults() -> None:
    assert Settings(_env_file=EXAMPLE).model_dump() == Settings(_env_file=None).model_dump()


def test_every_setting_is_documented_in_the_example_file() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    missing = [variable_name(f) for f in Settings.model_fields if f not in UNDOCUMENTED and variable_name(f) not in text]
    assert missing == []
    # The example never ships a key, real or fake.
    assert "ANTHROPIC_API_KEY=\n" in text and "sk-ant" not in text


def test_environment_variables_override_the_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SOURCEWISE_PORT=9000\nSOURCEWISE_TOP_K=4\nANTHROPIC_API_KEY=from-file-not-real\n", encoding="utf-8")
    monkeypatch.setenv("SOURCEWISE_PORT", "9001")
    settings = Settings(_env_file=env_file)
    assert (settings.port, settings.top_k) == (9001, 4)
    # The key keeps the name the Anthropic SDK uses, and its presence switches the engine.
    assert settings.anthropic_api_key == "from-file-not-real" and settings.resolved_engine == "claude"
    assert Settings(_env_file=env_file, engine="offline").resolved_engine == "offline"


def test_invalid_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, engine="gpt")
    with pytest.raises(ValueError):
        Settings(_env_file=None, retriever="elastic")
