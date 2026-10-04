"""Deterministic identifiers for the SYNTHETIC demo data (shared by seed and demo scripts)."""

from __future__ import annotations

import uuid

_NS = uuid.UUID("5b0c3c9e-8a7d-4f1e-9d2a-0c1b2a3d4e5f")


def demo_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_NS, name)


TENANT_NAME = "Smart Tech Ventures Demo"
TENANT_ID = demo_id("tenant:smart-tech-ventures-demo")
HEALTH_PARTICIPANT_ID = demo_id("participant:health-demo")
MENTORSHIP_PARTICIPANT_ID = demo_id("participant:mentorship-demo")
HEALTH_JOURNEY_ID = demo_id("journey:health-demo")
MENTORSHIP_JOURNEY_ID = demo_id("journey:mentorship-demo")
ADMIN_ACTOR = "admin.demo@smarttech.example"
MENTOR_ACTOR = "mentor.demo@smarttech.example"
HEALTH_PARTICIPANT_EMAIL = "participant.health@smarttech.example"
MENTORSHIP_PARTICIPANT_EMAIL = "participant.mentorship@smarttech.example"
# Website sign-in password for every SYNTHETIC demo account. Local-only, like the other
# defaults in .env.example: never reuse it anywhere else.
DEMO_PASSWORD = "cairn-demo-only"  # noqa: S105 - synthetic demo only


def participant_headers(participant_id: uuid.UUID) -> dict[str, str]:
    return {
        "X-Cairn-Actor": f"participant:{participant_id}",
        "X-Cairn-Tenant": str(TENANT_ID),
        "X-Cairn-Roles": "participant",
        "X-Cairn-Participant": str(participant_id),
    }


def admin_headers() -> dict[str, str]:
    return {
        "X-Cairn-Actor": ADMIN_ACTOR,
        "X-Cairn-Tenant": str(TENANT_ID),
        "X-Cairn-Roles": "tenant_admin",
    }
