"""Contract every shipped Domain Pack must satisfy."""

from __future__ import annotations

import re

import pytest

from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.registry import DomainPackRegistry
from cairn.policies.safety import SafetyPolicyValidator
from tests.conftest import REPO_ROOT

REGISTRY = DomainPackRegistry.from_directory(REPO_ROOT / "domain_packs")
PACKS = REGISTRY.all()


@pytest.fixture(params=PACKS, ids=[p.id for p in PACKS])
def pack(request: pytest.FixtureRequest) -> DomainPack:
    return request.param  # type: ignore[no-any-return]


def test_reference_packs_present() -> None:
    assert {p.id for p in PACKS} >= {"demo", "parkinsons", "mentorship"}


def test_semver_everywhere(pack: DomainPack) -> None:
    semver = re.compile(r"^\d+\.\d+\.\d+$")
    versions = [
        pack.version,
        pack.safety.version,
        pack.planner.version,
        pack.memory.version,
        *(p.version for p in pack.response_policies),
        *(q.version for q in pack.question_protocols),
        *(r.version for r in pack.patterns),
        *(s.version for s in pack.observation_schemas.values()),
    ]
    assert all(semver.match(v) for v in versions)


def test_pack_is_internally_consistent(pack: DomainPack) -> None:
    assert pack.validate_references() == []


def test_approved_wording_never_breaks_own_safety_rules(pack: DomainPack) -> None:
    """Every template, question and approved guidance passes the pack's prohibited-claim rules."""
    validator = SafetyPolicyValidator(pack)
    texts = [q.template for q in pack.questions.values()]
    texts += [t.text for p in pack.response_policies for t in p.templates]
    texts += [a.template for a in pack.activities.values()]
    texts += [g.text for g in pack.guidance.values() if g.approved]
    texts += [
        pack.planner.default_acknowledgement,
        pack.planner.end_session_template,
        pack.safety.safe_fallback_text,
        pack.safety.escalation_template,
    ]
    offending = [t for t in texts if validator.check_text(t)]
    assert offending == []


def test_health_packs_are_descriptive_and_labelled(pack: DomainPack) -> None:
    if pack.manifest.classification != "health":
        pytest.skip("not a health pack")
    assert pack.safety.descriptive_only
    assert pack.manifest.regulatory_profile == "descriptive_only"
    assert pack.manifest.synthetic_sample
    categories = {c.category for c in pack.safety.prohibited_claims}
    assert {"diagnosis", "treatment_recommendation"} <= categories
