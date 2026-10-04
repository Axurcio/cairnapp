"""Consent revocation propagation and evidence upload validation."""

from __future__ import annotations

import httpx
import pytest

from cairn.container import Container
from cairn.context.provider import ContextScope
from cairn.evidence.validation import EvidenceValidationError, validate_upload
from cairn.workflows.dispatcher import InlineWorkflowDispatcher
from tests.conftest import World

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def _upload(
    client: httpx.AsyncClient,
    world: World,
    data: bytes,
    content_type: str,
    retention: str = "standard",
) -> httpx.Response:
    return await client.post(
        f"/v1/journeys/{world.journey_id}/evidence",
        headers=world.participant_headers(),
        files={"file": ("x.bin", data, content_type)},
        data={"capture_type": "photo", "retention_class": retention},
    )


async def test_evidence_upload_stores_metadata_and_event(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("parkinsons")
    response = await _upload(client, world, PNG, "image/png")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["size_bytes"] == len(PNG)
    assert len(body["checksum_sha256"]) == 64
    key = f"{world.tenant_id}/{world.journey_id}/{body['id']}"
    assert await container.evidence_store.get(key) == PNG

    timeline = (
        await client.get(
            f"/v1/journeys/{world.journey_id}/timeline", headers=world.participant_headers()
        )
    ).json()
    assert timeline[-1]["event_type"] == "evidence.added"
    assert timeline[-1]["evidence_refs"] == [body["id"]]


@pytest.mark.parametrize(
    ("data", "content_type", "status"),
    [
        (b"not a png", "image/png", 422),  # magic bytes do not match
        (b"MZ\x90\x00", "application/x-msdownload", 415),  # type not allowed
        (b"", "text/plain", 422),  # empty
    ],
)
async def test_evidence_upload_rejects_bad_content(
    client: httpx.AsyncClient,
    world_factory,
    data: bytes,
    content_type: str,  # type: ignore[no-untyped-def]
    status: int,
) -> None:
    world: World = await world_factory("parkinsons")
    assert (await _upload(client, world, data, content_type)).status_code == status


def test_upload_size_limit() -> None:
    with pytest.raises(EvidenceValidationError) as err:
        validate_upload(b"a" * 11, "text/plain", allowed=["text/plain"], max_bytes=10)
    assert err.value.status_code == 413


async def test_consent_revocation_propagates_to_derived_stores(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("parkinsons")
    await client.post(
        f"/v1/journeys/{world.journey_id}/messages",
        json={"text": "My right hand has been shaky lately."},
        headers=world.participant_headers(),
    )
    kept = (await _upload(client, world, PNG, "image/png", "retain_for_audit")).json()
    deleted = (await _upload(client, world, PNG, "image/png", "delete_on_revocation")).json()
    scope = ContextScope(tenant_id=world.tenant_id, journey_id=world.journey_id)
    assert await container.context.recall(scope, "shaky hand")

    response = await client.post(
        f"/v1/journeys/{world.journey_id}/consent/revoke",
        json={"scopes": ["conversation"]},
        headers=world.participant_headers(),
    )
    assert response.status_code == 202
    assert response.json()["status"] == "completed"

    dispatcher = container.dispatcher
    assert isinstance(dispatcher, InlineWorkflowDispatcher)
    result = dispatcher.last_revocation
    assert result is not None
    assert result.revoked_consent_ids
    assert result.processing_restricted
    assert result.context_items_removed >= 1
    assert (result.evidence_deleted, result.evidence_retained) == (1, 1)
    assert result.audit_recorded

    # 2. further processing is prevented
    blocked = await client.post(
        f"/v1/journeys/{world.journey_id}/messages",
        json={"text": "Hello again"},
        headers=world.participant_headers(),
    )
    assert blocked.status_code == 409
    # 3. derived context is gone
    assert await container.context.recall(scope, "shaky hand") == []
    # 4. evidence removed per retention class
    with pytest.raises(FileNotFoundError):
        await container.evidence_store.get(f"{world.tenant_id}/{world.journey_id}/{deleted['id']}")
    assert (
        await container.evidence_store.get(f"{world.tenant_id}/{world.journey_id}/{kept['id']}")
        == PNG
    )
    # canonical record of what happened is preserved
    journey = (
        await client.get(f"/v1/journeys/{world.journey_id}", headers=world.admin_headers())
    ).json()
    assert journey["status"] == "processing_restricted"
