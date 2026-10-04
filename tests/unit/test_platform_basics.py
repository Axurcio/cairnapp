"""Settings, logging privacy, deterministic operation and Domain Pack loading."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import structlog

from cairn.config.settings import (
    AIProviderKind,
    AuthProviderKind,
    CairnSettings,
    Environment,
    RendererKind,
)
from cairn.container import Container
from cairn.domain_packs.loader import load_domain_pack
from cairn.domain_packs.pack import DomainPackError
from cairn.domain_packs.registry import DomainPackRegistry, DomainPackVersionMismatch
from cairn.observability.logging import configure_logging, get_logger
from tests.conftest import REPO_ROOT


def test_j_defaults_need_no_external_ai(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("CAIRN_AI_PROVIDER", "CAIRN_RENDERER", "CAIRN_OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    settings = CairnSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.ai_provider is AIProviderKind.MOCK
    assert settings.renderer is RendererKind.TEMPLATE
    assert settings.openai_api_key is None
    assert container.ai.name == "mock"
    assert container.renderer.name == "template"


def test_empty_api_key_is_unset() -> None:
    assert CairnSettings(_env_file=None, openai_api_key="").openai_api_key is None  # type: ignore[call-arg]


def test_production_refuses_dev_auth() -> None:
    with pytest.raises(ValueError, match="dev auth"):
        CairnSettings(
            _env_file=None,
            env=Environment.PRODUCTION,  # type: ignore[call-arg]
            auth_provider=AuthProviderKind.DEV,
            database_url="postgresql+asyncpg://u:p@db/cairn",
        )


def test_logs_redact_sensitive_content(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)
    get_logger("t").info(
        "journey.message.received", text="My hand shakes", chars=14, payload={"text": "secret"}
    )
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["text"] == "[redacted]"
    assert line["payload"] == "[redacted]"
    assert line["chars"] == 14
    structlog.reset_defaults()


def test_pack_version_pinning(registry: DomainPackRegistry) -> None:
    assert registry.resolve_for_journey("parkinsons", "0.0.9").version == "0.1.0"
    with pytest.raises(DomainPackVersionMismatch):
        registry.resolve_for_journey("parkinsons", "1.0.0")


def _copy_pack(tmp_path: Path, pack_id: str) -> Path:
    target = tmp_path / pack_id
    shutil.copytree(REPO_ROOT / "domain_packs" / pack_id, target)
    return target


def test_pack_with_missing_question_is_rejected(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path, "demo")
    questions = pack / "questions" / "reading.yaml"
    questions.write_text(questions.read_text().replace("collects: enjoyment", "collects: genre"))
    with pytest.raises(DomainPackError, match="no question collects 'enjoyment'"):
        load_domain_pack(pack)


def test_pack_referencing_unapproved_guidance_is_rejected(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path, "demo")
    policy = pack / "responses" / "reading_followup.yaml"
    policy.write_text(
        policy.read_text().replace("guidance_ids: [reading_tip]", "guidance_ids: [draft_tip]")
    )
    with pytest.raises(DomainPackError, match="not approved"):
        load_domain_pack(pack)


def test_pack_with_invalid_semver_is_rejected(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path, "demo")
    manifest = pack / "manifest.yaml"
    manifest.write_text(manifest.read_text().replace("version: 1.0.0", "version: latest"))
    with pytest.raises(DomainPackError, match="schema validation failed"):
        load_domain_pack(pack)
