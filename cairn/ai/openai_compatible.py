"""Provider for any OpenAI-compatible ``/chat/completions`` endpoint.

Works with OpenAI, Azure-style gateways, vLLM, Ollama, LiteLLM, etc. It uses plain
``httpx`` rather than a vendor SDK so no business module depends on one.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from cairn.ai.prompts import extraction_messages, render_messages
from cairn.ai.provider import AIProviderError, AIResponse, ExtractionRequest, RawExtraction
from cairn.planner.intents import ResponseIntent


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )

    async def _chat(self, messages: list[dict[str, str]], *, json_mode: bool) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            response = await self._client.post("/chat/completions", json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIProviderError(f"{self.name} request failed: {exc}") from exc
        data: dict[str, Any] = response.json()
        return data

    async def extract(self, request: ExtractionRequest) -> RawExtraction:
        data = await self._chat(extraction_messages(request), json_mode=True)
        content = data["choices"][0]["message"]["content"]
        try:
            output = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIProviderError(f"extraction output is not JSON: {exc}") from exc
        if not isinstance(output, dict):
            raise AIProviderError("extraction output is not a JSON object")
        return RawExtraction(output=output, provider=self.name, model=self.model)

    async def render_response(self, intent: ResponseIntent) -> AIResponse:
        data = await self._chat(render_messages(intent), json_mode=False)
        choice = data["choices"][0]
        return AIResponse(
            text=choice["message"]["content"].strip(),
            provider=self.name,
            model=data.get("model", self.model),
            finish_reason=choice.get("finish_reason"),
            usage={k: v for k, v in (data.get("usage") or {}).items() if isinstance(v, int)},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
