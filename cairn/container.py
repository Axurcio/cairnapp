"""Composition root: wires providers to implementations based on settings.

This is the only module that chooses concrete implementations. Business code
receives protocols (AIProvider, ResponseRenderer, GuardrailProvider,
ContextMemoryProvider, EvidenceStore, WorkflowDispatcher, PolicyDecisionProvider).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cairn.ai.extraction import ExtractionService
from cairn.ai.mock import MockAIProvider
from cairn.ai.openai_compatible import OpenAICompatibleProvider
from cairn.ai.provider import AIProvider
from cairn.ai.rendering import DeterministicTemplateRenderer, LLMResponseRenderer, ResponseRenderer
from cairn.auth.decisions import CairnPolicyDecisionProvider, PolicyDecisionProvider
from cairn.auth.dev_provider import DevAuthProvider
from cairn.config.settings import (
    AIProviderKind,
    CairnSettings,
    ContextProviderKind,
    EvidenceStoreKind,
    GuardrailProviderKind,
    RendererKind,
    WorkflowDispatcherKind,
)
from cairn.context.in_memory import InMemoryContextProvider
from cairn.context.projection import ContextProjectionService
from cairn.context.provider import ContextMemoryProvider
from cairn.domain_packs.registry import DomainPackRegistry
from cairn.evidence.store import EvidenceStore, LocalEvidenceStore, MinioEvidenceStore
from cairn.guardrails.noop import NoOpGuardrailProvider
from cairn.guardrails.provider import GuardrailProvider
from cairn.persistence.database import create_engine, create_sessionmaker
from cairn.workflows.activities import CairnActivities
from cairn.workflows.dispatcher import (
    InlineWorkflowDispatcher,
    TemporalWorkflowDispatcher,
    WorkflowDispatcher,
)


@dataclass
class Container:
    settings: CairnSettings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    packs: DomainPackRegistry
    ai: AIProvider
    extraction: ExtractionService
    renderer: ResponseRenderer
    guardrails: GuardrailProvider
    context: ContextMemoryProvider
    projection: ContextProjectionService
    evidence_store: EvidenceStore
    activities: CairnActivities
    dispatcher: WorkflowDispatcher
    authz: PolicyDecisionProvider
    auth: DevAuthProvider

    async def aclose(self) -> None:
        await self.dispatcher.aclose()
        await self.context.aclose()
        await self.ai.aclose()
        await self.engine.dispose()


def build_ai_provider(settings: CairnSettings) -> AIProvider:
    if settings.ai_provider is AIProviderKind.OPENAI_COMPATIBLE:
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAICompatibleProvider(
            base_url=settings.openai_base_url,
            api_key=key,
            model=settings.openai_model,
            timeout=settings.ai_timeout_seconds,
        )
    return MockAIProvider()


def build_context_provider(settings: CairnSettings) -> ContextMemoryProvider:
    match settings.context_provider:
        case ContextProviderKind.GRAPHITI:
            from cairn.context.graphiti import GraphitiContextProvider, create_graphiti_client

            key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
            client = create_graphiti_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password.get_secret_value(),
                mode=settings.graphiti_mode.value,
                llm_api_key=key,
                llm_base_url=settings.openai_base_url,
                llm_model=settings.openai_model,
            )
            return GraphitiContextProvider(client, mode=settings.graphiti_mode.value)
        case ContextProviderKind.HINDSIGHT:
            raise ValueError(
                "HindsightContextProvider is a documented placeholder; choose in_memory or graphiti"
            )
        case _:
            return InMemoryContextProvider()


def build_guardrails(settings: CairnSettings) -> GuardrailProvider:
    if settings.guardrail_provider is GuardrailProviderKind.NEMO:
        from cairn.guardrails.nemo import NeMoGuardrailProvider

        return NeMoGuardrailProvider.from_config_path(settings.nemo_config_path)
    return NoOpGuardrailProvider()


def build_evidence_store(settings: CairnSettings) -> EvidenceStore:
    if settings.evidence_store is EvidenceStoreKind.MINIO:
        return MinioEvidenceStore(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key.get_secret_value(),
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    return LocalEvidenceStore(settings.local_evidence_path)


def build_container(
    settings: CairnSettings,
    *,
    context: ContextMemoryProvider | None = None,
    ai: AIProvider | None = None,
    guardrails: GuardrailProvider | None = None,
    evidence_store: EvidenceStore | None = None,
    dispatcher: WorkflowDispatcher | None = None,
) -> Container:
    engine = create_engine(settings.database_url, echo=settings.database_echo)
    sessionmaker = create_sessionmaker(engine)
    packs = DomainPackRegistry.from_directory(settings.domain_packs_path)
    ai = ai or build_ai_provider(settings)
    renderer: ResponseRenderer = (
        LLMResponseRenderer(ai)
        if settings.renderer is RendererKind.LLM
        else DeterministicTemplateRenderer()
    )
    context = context or build_context_provider(settings)
    projection = ContextProjectionService(sessionmaker, packs, context)
    evidence_store = evidence_store or build_evidence_store(settings)
    activities = CairnActivities(
        sessionmaker=sessionmaker, packs=packs, projection=projection, evidence_store=evidence_store
    )
    if dispatcher is None:
        dispatcher = (
            TemporalWorkflowDispatcher(
                address=settings.temporal_address,
                namespace=settings.temporal_namespace,
                task_queue=settings.temporal_task_queue,
            )
            if settings.workflow_dispatcher is WorkflowDispatcherKind.TEMPORAL
            else InlineWorkflowDispatcher(activities)
        )
    return Container(
        settings=settings,
        engine=engine,
        sessionmaker=sessionmaker,
        packs=packs,
        ai=ai,
        extraction=ExtractionService(ai, max_attempts=settings.extraction_max_attempts),
        renderer=renderer,
        guardrails=guardrails or build_guardrails(settings),
        context=context,
        projection=projection,
        evidence_store=evidence_store,
        activities=activities,
        dispatcher=dispatcher,
        authz=CairnPolicyDecisionProvider(),
        auth=DevAuthProvider(),
    )
