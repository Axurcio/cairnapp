"""Response renderers: turn a decided ResponseIntent into words.

* :class:`DeterministicTemplateRenderer` - approved wording, verbatim. Default.
* :class:`LLMResponseRenderer` - lets an AIProvider phrase the intent within its
  limits, then appends approved guidance verbatim. Falls back to the template if
  variation is not allowed, the provider fails, or the output breaks the limits.
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel

from cairn.ai.provider import AIProvider, AIProviderError
from cairn.observability.logging import get_logger
from cairn.planner.intents import ResponseIntent

log = get_logger(__name__)

_SENTENCE_END = re.compile(r"[.!?](\s|$)")


class RenderedResponse(BaseModel):
    text: str
    renderer: str
    provider: str | None = None
    model: str | None = None
    fallback_reason: str | None = None


class ResponseRenderer(Protocol):
    name: str

    async def render(self, intent: ResponseIntent) -> RenderedResponse: ...


def _with_guidance(text: str, intent: ResponseIntent) -> str:
    return " ".join([text, *(g.text.strip() for g in intent.guidance)]).strip()


def deterministic_text(intent: ResponseIntent) -> str:
    body = " ".join(p for p in (intent.preamble, intent.deterministic_text) if p)
    return _with_guidance(body, intent)


class DeterministicTemplateRenderer:
    name = "template"

    async def render(self, intent: ResponseIntent) -> RenderedResponse:
        return RenderedResponse(text=deterministic_text(intent), renderer=self.name)


class LLMResponseRenderer:
    name = "llm"

    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider
        self._fallback = DeterministicTemplateRenderer()

    async def render(self, intent: ResponseIntent) -> RenderedResponse:
        if not intent.allow_llm_variation:
            return await self._fallback_with("llm variation not allowed by policy", intent)
        try:
            response = await self._provider.render_response(intent)
        except AIProviderError as exc:
            log.warning("render.provider_failed", error=str(exc))
            return await self._fallback_with("provider error", intent)

        text = response.text.strip()
        # Preamble counts toward the sentence budget.
        allowed = intent.max_sentences + (1 if intent.preamble else 0)
        if not text or len(_SENTENCE_END.findall(text + " ")) > allowed:
            return await self._fallback_with("output exceeded sentence limit or was empty", intent)
        if intent.kind == "ASK_QUESTION" and "?" not in text:
            return await self._fallback_with("question intent rendered without a question", intent)
        return RenderedResponse(
            text=_with_guidance(text, intent),
            renderer=self.name,
            provider=response.provider,
            model=response.model,
        )

    async def _fallback_with(self, reason: str, intent: ResponseIntent) -> RenderedResponse:
        rendered = await self._fallback.render(intent)
        return rendered.model_copy(update={"fallback_reason": reason})
