"""Runtime configuration, read from environment variables and an optional ``.env`` file.

Every setting has a working default, so ``python -m sourcewise serve`` runs with zero
configuration. Variables are prefixed ``SOURCEWISE_`` except ``ANTHROPIC_API_KEY``, which
keeps the name the Anthropic SDK itself uses.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SOURCEWISE_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- server -------------------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8102
    data_dir: Path = PROJECT_ROOT / "data"
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"
    corpus_dir: Path = PROJECT_ROOT / "corpus"
    session_ttl_hours: int = 168
    cookie_secure: bool = False  # set true when served over HTTPS
    max_upload_mb: int = 10
    # Show the seeded demo sign-in details on the login page. Turn off for anything but a demo.
    show_demo_accounts: bool = True

    # --- ingestion ----------------------------------------------------------------------
    chunk_max_chars: int = 700  # roughly 175 tokens
    chunk_overlap_chars: int = 150

    # --- retrieval ----------------------------------------------------------------------
    retriever: Literal["auto", "fts5", "bm25"] = "auto"
    top_k: int = 6
    # Abstention gate (see sourcewise/answering/confidence.py). The assistant answers only if
    # the best passage contains at least `min_coverage` of the question's IDF-weighted terms
    # (chosen on eval/dev_set.json) and at least `min_evidence` rare terms' worth of them (a
    # floor that stops a match on one ubiquitous word, such as "staff", from counting).
    min_coverage: float = 0.55
    min_evidence: float = 0.5
    # Coverage threshold when the answer engine is Claude. The model reads the passages and
    # declines by itself when they do not answer the question, so for that engine the gate
    # only has to keep clearly unrelated questions from costing an API call; the evidence
    # floor above still applies. A paraphrased question ("the most I can spend on a hotel"
    # for "hotel limit per night") falls below the strict threshold although the right
    # passage was retrieved. Set this to the value of `min_coverage` to send Claude only what
    # the extractive engine would be given.
    claude_min_coverage: float = 0.25

    # --- answering ----------------------------------------------------------------------
    engine: Literal["auto", "offline", "claude"] = "auto"
    anthropic_api_key: str | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
    claude_model: str = "claude-opus-5-5"
    claude_max_tokens: int = 16000
    # low | medium | high | xhigh | max, or "none" to omit the parameter for models without effort support.
    claude_effort: str = "medium"
    # Server-side refusal fallback (beta). "auto" enables it for the models that support it.
    claude_refusal_fallback: Literal["auto", "on", "off"] = "auto"
    claude_timeout_seconds: float = 120.0
    # If the Claude call fails (rate limit, network, bad key), answer in extractive mode instead of erroring.
    fallback_to_offline: bool = True
    # Pacing of the offline engine's streamed output, in milliseconds per word (0 disables).
    stream_delay_ms: int = 12

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'sourcewise.db').as_posix()}"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def resolved_engine(self) -> Literal["offline", "claude"]:
        """Which answer engine to use: Claude when a key is configured, otherwise offline."""
        if self.engine == "auto":
            return "claude" if self.anthropic_api_key else "offline"
        return self.engine


@lru_cache
def get_settings() -> Settings:
    return Settings()
