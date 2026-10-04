"""Typed application settings.

All runtime configuration flows through :class:`CairnSettings`. Values come from
environment variables prefixed ``CAIRN_`` (and an optional ``.env`` file). The
defaults boot a fully local, credential-free stack: MockAIProvider, template
rendering, no-op guardrails, in-memory context and inline workflow dispatch.
Docker Compose overrides these to use Postgres, Graphiti/Neo4j, MinIO and Temporal.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class AIProviderKind(StrEnum):
    MOCK = "mock"
    OPENAI_COMPATIBLE = "openai_compatible"


class RendererKind(StrEnum):
    TEMPLATE = "template"
    LLM = "llm"


class ContextProviderKind(StrEnum):
    IN_MEMORY = "in_memory"
    GRAPHITI = "graphiti"
    HINDSIGHT = "hindsight"


class GraphitiMode(StrEnum):
    # Store raw episodes only; no LLM/embedder needed. Default for local dev.
    EPISODES = "episodes"
    # Full Graphiti entity/fact extraction; requires LLM + embedder credentials.
    FULL = "full"


class GuardrailProviderKind(StrEnum):
    NOOP = "noop"
    NEMO = "nemo"


class EvidenceStoreKind(StrEnum):
    LOCAL = "local"
    MINIO = "minio"


class WorkflowDispatcherKind(StrEnum):
    INLINE = "inline"
    TEMPORAL = "temporal"


class AuthProviderKind(StrEnum):
    # Browser sessions plus identity from X-Cairn-* headers (local development only).
    DEV = "dev"
    # Browser sessions (username/password login) only.
    SESSION = "session"


class CairnSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAIRN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment = Environment.LOCAL
    service_name: str = "cairn"

    # --- persistence -------------------------------------------------------
    database_url: str = "postgresql+asyncpg://cairn:cairn_local_dev_only@localhost:5432/cairn"
    database_echo: bool = False

    # --- domain packs ------------------------------------------------------
    domain_packs_path: Path = REPO_ROOT / "domain_packs"

    # --- AI gateway --------------------------------------------------------
    ai_provider: AIProviderKind = AIProviderKind.MOCK
    renderer: RendererKind = RendererKind.TEMPLATE
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 30.0
    extraction_max_attempts: int = Field(default=2, ge=1, le=5)

    # --- context memory (derived projection) -------------------------------
    context_provider: ContextProviderKind = ContextProviderKind.IN_MEMORY
    graphiti_mode: GraphitiMode = GraphitiMode.EPISODES
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("cairn_local_dev_only")
    context_recall_limit: int = 5

    # --- guardrails --------------------------------------------------------
    guardrail_provider: GuardrailProviderKind = GuardrailProviderKind.NOOP
    nemo_config_path: Path = REPO_ROOT / "cairn" / "guardrails" / "nemo_config"

    # --- evidence ----------------------------------------------------------
    evidence_store: EvidenceStoreKind = EvidenceStoreKind.LOCAL
    local_evidence_path: Path = REPO_ROOT / ".data" / "evidence"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "cairn"
    minio_secret_key: SecretStr = SecretStr("cairn_local_dev_only")
    minio_bucket: str = "cairn-evidence"
    minio_secure: bool = False
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_evidence_content_types: list[str] = Field(
        default_factory=lambda: [
            "image/jpeg",
            "image/png",
            "application/pdf",
            "text/plain",
            "application/json",
            "audio/mpeg",
            "audio/wav",
            "video/mp4",
        ]
    )

    # --- workflows ---------------------------------------------------------
    workflow_dispatcher: WorkflowDispatcherKind = WorkflowDispatcherKind.INLINE
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "cairn-journeys"
    journey_follow_up_hours: float = 72.0

    # --- auth --------------------------------------------------------------
    auth_provider: AuthProviderKind = AuthProviderKind.DEV
    session_cookie_name: str = "cairn_session"
    # Must be true whenever the site is served over HTTPS (required in production).
    session_cookie_secure: bool = False
    session_ttl_hours: float = Field(default=12.0, gt=0, le=24 * 30)

    # --- observability -----------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True
    # Never enable outside local debugging: allows raw participant text in logs.
    log_sensitive: bool = False
    otel_enabled: bool = False
    otel_console_exporter: bool = False

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _empty_key_is_unset(cls, value: object) -> object:
        # Compose passes unset variables as empty strings.
        return None if value in ("", None) else value

    @model_validator(mode="after")
    def _guard_production(self) -> CairnSettings:
        if self.env is Environment.PRODUCTION:
            if self.auth_provider is AuthProviderKind.DEV:
                raise ValueError("The dev auth provider must not be used in production.")
            if not self.session_cookie_secure:
                raise ValueError("session_cookie_secure must be true in production.")
            if self.log_sensitive:
                raise ValueError("log_sensitive must be false in production.")
            if "local_dev_only" in self.database_url:
                raise ValueError("Local development database credentials used in production.")
        return self


@lru_cache
def get_settings() -> CairnSettings:
    return CairnSettings()
