"""Initial canonical schema.

Canonical Cairn data lives here and is authoritative. Derived context (Graphiti)
is NOT stored in Postgres and is never migrated - it is rebuilt from these tables.

JSONB is used only for Domain-Pack-specific payloads; identity, tenancy, typing and
timing are real columns with indexes on tenant_id, journey_id, participant_id and
occurred_at. The pgvector extension is enabled for future semantic features over
canonical data; no vector columns are defined yet.

Revision ID: 0001
Revises:
Create Date: 2026-10-04 06:28:06.093501+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        op.f("ix_audit_events_occurred_at"), "audit_events", ["occurred_at"], unique=False
    )
    op.create_index(op.f("ix_audit_events_tenant_id"), "audit_events", ["tenant_id"], unique=False)
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
    )
    op.create_table(
        "participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("external_ref", sa.String(length=200), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_participants_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participants")),
    )
    op.create_index(op.f("ix_participants_tenant_id"), "participants", ["tenant_id"], unique=False)
    op.create_table(
        "journeys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("domain_pack", sa.String(length=100), nullable=False),
        sa.Column("domain_pack_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_journeys_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_journeys_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journeys")),
    )
    op.create_index(
        op.f("ix_journeys_participant_id"), "journeys", ["participant_id"], unique=False
    )
    op.create_index(op.f("ix_journeys_tenant_id"), "journeys", ["tenant_id"], unique=False)
    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["journeys.id"],
            name=op.f("fk_consents_journey_id_journeys"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_consents_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_consents_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
    )
    op.create_index(op.f("ix_consents_journey_id"), "consents", ["journey_id"], unique=False)
    op.create_index(
        op.f("ix_consents_participant_id"), "consents", ["participant_id"], unique=False
    )
    op.create_index(op.f("ix_consents_tenant_id"), "consents", ["tenant_id"], unique=False)
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("capture_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("consent_scope", sa.String(length=64), nullable=False),
        sa.Column("retention_class", sa.String(length=64), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("domain_pack", sa.String(length=100), nullable=True),
        sa.Column("domain_pack_version", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["journeys.id"],
            name=op.f("fk_evidence_journey_id_journeys"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_evidence_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
        sa.UniqueConstraint("object_key", name=op.f("uq_evidence_object_key")),
    )
    op.create_index(op.f("ix_evidence_journey_id"), "evidence", ["journey_id"], unique=False)
    op.create_index(op.f("ix_evidence_occurred_at"), "evidence", ["occurred_at"], unique=False)
    op.create_index(
        op.f("ix_evidence_participant_id"), "evidence", ["participant_id"], unique=False
    )
    op.create_index(op.f("ix_evidence_tenant_id"), "evidence", ["tenant_id"], unique=False)
    op.create_table(
        "journey_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("consent_scope", sa.String(length=64), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("domain_pack", sa.String(length=100), nullable=True),
        sa.Column("domain_pack_version", sa.String(length=32), nullable=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["journeys.id"],
            name=op.f("fk_journey_events_journey_id_journeys"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_journey_events_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journey_events")),
    )
    op.create_index(
        op.f("ix_journey_events_journey_id"), "journey_events", ["journey_id"], unique=False
    )
    op.create_index(
        op.f("ix_journey_events_occurred_at"), "journey_events", ["occurred_at"], unique=False
    )
    op.create_index(
        op.f("ix_journey_events_participant_id"), "journey_events", ["participant_id"], unique=False
    )
    op.create_index(
        op.f("ix_journey_events_tenant_id"), "journey_events", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_journey_events_tenant_journey_occurred",
        "journey_events",
        ["tenant_id", "journey_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("observation_type", sa.String(length=100), nullable=False),
        sa.Column("observation_schema_version", sa.String(length=32), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_event_ids", postgresql.JSONB(), nullable=False),
        sa.Column("source_evidence_ids", postgresql.JSONB(), nullable=False),
        sa.Column("field_provenance", postgresql.JSONB(), nullable=False),
        sa.Column("extraction_version", sa.String(length=32), nullable=False),
        sa.Column("domain_pack", sa.String(length=100), nullable=True),
        sa.Column("domain_pack_version", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["journeys.id"],
            name=op.f("fk_observations_journey_id_journeys"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_observations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observations")),
    )
    op.create_index(
        op.f("ix_observations_journey_id"), "observations", ["journey_id"], unique=False
    )
    op.create_index(
        op.f("ix_observations_occurred_at"), "observations", ["occurred_at"], unique=False
    )
    op.create_index(
        op.f("ix_observations_participant_id"), "observations", ["participant_id"], unique=False
    )
    op.create_index(op.f("ix_observations_tenant_id"), "observations", ["tenant_id"], unique=False)
    op.create_index(
        "ix_observations_tenant_journey_type_occurred",
        "observations",
        ["tenant_id", "journey_id", "observation_type", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "pattern_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("suggested_action", sa.String(length=100), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("source_event_ids", postgresql.JSONB(), nullable=False),
        sa.Column("domain_pack", sa.String(length=100), nullable=True),
        sa.Column("domain_pack_version", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["journeys.id"],
            name=op.f("fk_pattern_evaluations_journey_id_journeys"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_pattern_evaluations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pattern_evaluations")),
    )
    op.create_index(
        op.f("ix_pattern_evaluations_journey_id"),
        "pattern_evaluations",
        ["journey_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pattern_evaluations_occurred_at"),
        "pattern_evaluations",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pattern_evaluations_participant_id"),
        "pattern_evaluations",
        ["participant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pattern_evaluations_tenant_id"), "pattern_evaluations", ["tenant_id"], unique=False
    )
    op.create_table(
        "relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["journeys.id"],
            name=op.f("fk_relationships_journey_id_journeys"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_relationships_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_relationships_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relationships")),
    )
    op.create_index(op.f("ix_relationships_actor_id"), "relationships", ["actor_id"], unique=False)
    op.create_index(
        op.f("ix_relationships_journey_id"), "relationships", ["journey_id"], unique=False
    )
    op.create_index(
        op.f("ix_relationships_participant_id"), "relationships", ["participant_id"], unique=False
    )
    op.create_index(
        op.f("ix_relationships_tenant_id"), "relationships", ["tenant_id"], unique=False
    )
    op.create_table(
        "next_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("question_id", sa.String(length=200), nullable=True),
        sa.Column("field", sa.String(length=100), nullable=True),
        sa.Column("activity_id", sa.String(length=100), nullable=True),
        sa.Column("observation_id", sa.Uuid(), nullable=True),
        sa.Column("policy_id", sa.String(length=100), nullable=True),
        sa.Column("policy_version", sa.String(length=32), nullable=True),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("explanation", postgresql.JSONB(), nullable=False),
        sa.Column("domain_pack", sa.String(length=100), nullable=True),
        sa.Column("domain_pack_version", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["journeys.id"],
            name=op.f("fk_next_actions_journey_id_journeys"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["observations.id"],
            name=op.f("fk_next_actions_observation_id_observations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_next_actions_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_next_actions")),
    )
    op.create_index(
        op.f("ix_next_actions_journey_id"), "next_actions", ["journey_id"], unique=False
    )
    op.create_index(
        op.f("ix_next_actions_occurred_at"), "next_actions", ["occurred_at"], unique=False
    )
    op.create_index(
        op.f("ix_next_actions_participant_id"), "next_actions", ["participant_id"], unique=False
    )
    op.create_index(op.f("ix_next_actions_tenant_id"), "next_actions", ["tenant_id"], unique=False)
    op.create_index(
        "ix_next_actions_tenant_journey_status",
        "next_actions",
        ["tenant_id", "journey_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_next_actions_tenant_journey_status", table_name="next_actions")
    op.drop_index(op.f("ix_next_actions_tenant_id"), table_name="next_actions")
    op.drop_index(op.f("ix_next_actions_participant_id"), table_name="next_actions")
    op.drop_index(op.f("ix_next_actions_occurred_at"), table_name="next_actions")
    op.drop_index(op.f("ix_next_actions_journey_id"), table_name="next_actions")
    op.drop_table("next_actions")
    op.drop_index(op.f("ix_relationships_tenant_id"), table_name="relationships")
    op.drop_index(op.f("ix_relationships_participant_id"), table_name="relationships")
    op.drop_index(op.f("ix_relationships_journey_id"), table_name="relationships")
    op.drop_index(op.f("ix_relationships_actor_id"), table_name="relationships")
    op.drop_table("relationships")
    op.drop_index(op.f("ix_pattern_evaluations_tenant_id"), table_name="pattern_evaluations")
    op.drop_index(op.f("ix_pattern_evaluations_participant_id"), table_name="pattern_evaluations")
    op.drop_index(op.f("ix_pattern_evaluations_occurred_at"), table_name="pattern_evaluations")
    op.drop_index(op.f("ix_pattern_evaluations_journey_id"), table_name="pattern_evaluations")
    op.drop_table("pattern_evaluations")
    op.drop_index("ix_observations_tenant_journey_type_occurred", table_name="observations")
    op.drop_index(op.f("ix_observations_tenant_id"), table_name="observations")
    op.drop_index(op.f("ix_observations_participant_id"), table_name="observations")
    op.drop_index(op.f("ix_observations_occurred_at"), table_name="observations")
    op.drop_index(op.f("ix_observations_journey_id"), table_name="observations")
    op.drop_table("observations")
    op.drop_index("ix_journey_events_tenant_journey_occurred", table_name="journey_events")
    op.drop_index(op.f("ix_journey_events_tenant_id"), table_name="journey_events")
    op.drop_index(op.f("ix_journey_events_participant_id"), table_name="journey_events")
    op.drop_index(op.f("ix_journey_events_occurred_at"), table_name="journey_events")
    op.drop_index(op.f("ix_journey_events_journey_id"), table_name="journey_events")
    op.drop_table("journey_events")
    op.drop_index(op.f("ix_evidence_tenant_id"), table_name="evidence")
    op.drop_index(op.f("ix_evidence_participant_id"), table_name="evidence")
    op.drop_index(op.f("ix_evidence_occurred_at"), table_name="evidence")
    op.drop_index(op.f("ix_evidence_journey_id"), table_name="evidence")
    op.drop_table("evidence")
    op.drop_index(op.f("ix_consents_tenant_id"), table_name="consents")
    op.drop_index(op.f("ix_consents_participant_id"), table_name="consents")
    op.drop_index(op.f("ix_consents_journey_id"), table_name="consents")
    op.drop_table("consents")
    op.drop_index(op.f("ix_journeys_tenant_id"), table_name="journeys")
    op.drop_index(op.f("ix_journeys_participant_id"), table_name="journeys")
    op.drop_table("journeys")
    op.drop_index(op.f("ix_participants_tenant_id"), table_name="participants")
    op.drop_table("participants")
    op.drop_table("tenants")
    op.drop_index(op.f("ix_audit_events_tenant_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_occurred_at"), table_name="audit_events")
    op.drop_table("audit_events")
