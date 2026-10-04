"""Load Domain Packs from disk.

Layout (by convention, all YAML)::

    <pack>/manifest.yaml
    <pack>/observations/*.yaml   key: observation
    <pack>/questions/*.yaml      key: question_protocol
    <pack>/responses/*.yaml      key: response_policy
    <pack>/patterns/*.yaml       key: pattern
    <pack>/activities/*.yaml     key: activities  (list)
    <pack>/safety/*.yaml         key: safety_policy (exactly one) | guidance (list)
    <pack>/planner/*.yaml        key: planner (exactly one)
    <pack>/reports/*.yaml        key: report_template
    <pack>/memory/*.yaml         key: memory (exactly one)
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from cairn.domain_packs.pack import DomainPack, DomainPackError
from cairn.domain_packs.schemas import (
    ActivityDefinition,
    ApprovedGuidance,
    DomainPackManifest,
    MemoryConfig,
    ObservationSchema,
    PackModel,
    PatternRule,
    PlannerConfig,
    QuestionProtocol,
    ReportTemplate,
    ResponsePolicy,
    SafetyPolicyConfig,
)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise DomainPackError(f"{path}: expected a mapping at the top level")
    return data


def _yaml_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])


def _section(path: Path, data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise DomainPackError(f"{path}: expected top-level key '{key}'")
    return data[key]


def load_domain_pack(root: Path) -> DomainPack:
    root = root.resolve()
    manifest_path = root / "manifest.yaml"
    if not manifest_path.exists():
        raise DomainPackError(f"{root}: missing manifest.yaml")

    digest = hashlib.sha256()
    files = [manifest_path, *sorted(p for p in root.rglob("*.y*ml") if p != manifest_path)]
    for f in files:
        digest.update(f.relative_to(root).as_posix().encode())
        digest.update(f.read_bytes())

    try:
        manifest = DomainPackManifest.model_validate(_read_yaml(manifest_path))
        if manifest.id != root.name:
            raise DomainPackError(f"{root}: manifest id '{manifest.id}' must match directory")

        observations: dict[str, ObservationSchema] = {}
        for path in _yaml_files(root / "observations"):
            schema = ObservationSchema.model_validate(
                _section(path, _read_yaml(path), "observation")
            )
            if schema.observation_type in observations:
                raise DomainPackError(f"{path}: duplicate observation '{schema.observation_type}'")
            observations[schema.observation_type] = schema

        protocols = [
            QuestionProtocol.model_validate(_section(p, _read_yaml(p), "question_protocol"))
            for p in _yaml_files(root / "questions")
        ]
        policies = [
            ResponsePolicy.model_validate(_section(p, _read_yaml(p), "response_policy"))
            for p in _yaml_files(root / "responses")
        ]
        patterns = [
            PatternRule.model_validate(_section(p, _read_yaml(p), "pattern"))
            for p in _yaml_files(root / "patterns")
        ]
        activities: dict[str, ActivityDefinition] = {}
        for path in _yaml_files(root / "activities"):
            for item in _section(path, _read_yaml(path), "activities"):
                activity = ActivityDefinition.model_validate(item)
                activities[activity.id] = activity

        safety: SafetyPolicyConfig | None = None
        guidance: dict[str, ApprovedGuidance] = {}
        for path in _yaml_files(root / "safety"):
            data = _read_yaml(path)
            if "safety_policy" in data:
                if safety is not None:
                    raise DomainPackError(f"{path}: more than one safety_policy")
                safety = SafetyPolicyConfig.model_validate(data["safety_policy"])
            for item in data.get("guidance", []):
                g = ApprovedGuidance.model_validate(item)
                guidance[g.id] = g
        if safety is None:
            raise DomainPackError(f"{root}: a safety_policy is required")

        planner = _single(root / "planner", "planner", PlannerConfig)
        memory = _single(root / "memory", "memory", MemoryConfig)
        reports = {
            t.id: t
            for t in (
                ReportTemplate.model_validate(_section(p, _read_yaml(p), "report_template"))
                for p in _yaml_files(root / "reports")
            )
        }
    except ValidationError as exc:
        raise DomainPackError(f"{root}: schema validation failed:\n{exc}") from exc

    pack = DomainPack(
        manifest=manifest,
        observation_schemas=observations,
        question_protocols=protocols,
        response_policies=policies,
        patterns=patterns,
        activities=activities,
        safety=safety,
        guidance=guidance,
        planner=planner,
        reports=reports,
        memory=memory,
        checksum=digest.hexdigest(),
    )
    problems = pack.validate_references()
    if problems:
        raise DomainPackError(f"{root}: inconsistent pack:\n  - " + "\n  - ".join(problems))
    return pack


def _single[T: PackModel](directory: Path, key: str, model: type[T]) -> T:
    files = _yaml_files(directory)
    if len(files) != 1:
        raise DomainPackError(f"{directory}: expected exactly one {key} file, found {len(files)}")
    return model.model_validate(_section(files[0], _read_yaml(files[0]), key))
