from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI


class NgamiaError(Exception):
    """Raised when the Ngamia gateway rejects a chat completion."""


class NgamiaClient:
    """Thin wrapper over the Ngamia OpenAI-compatible gateway.

    Ngamia (https://docs.ngamia.cc) mirrors OpenAI's wire format at
    https://api.ngamia.cc/v1 with a single ngm_... key, so the official
    OpenAI SDK works unmodified. Model ids come from GET /v1/models and are
    passed through verbatim.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        if not api_key:
            raise NgamiaError("NGAMIA_API_KEY is required")
        self.model = model
        self._client = AsyncOpenAI(base_url=base_url.rstrip("/"), api_key=api_key, timeout=timeout)

    async def list_models(self) -> list[str]:
        try:
            models = await self._client.models.list()
        except Exception as exc:  # pragma: no cover - gateway dependent
            raise NgamiaError(f"list models failed: {exc}") from exc
        # Each catalog row exposes both `id` (internal row id) and `model`
        # (the value to pass to chat completions). Only `model` is callable.
        return [getattr(m, "model", None) or m.id for m in models.data]

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1000,
        temperature: float = 0.6,
    ) -> str:
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            raise NgamiaError(f"chat completion failed: {exc}") from exc
        content = resp.choices[0].message.content
        if not content:
            raise NgamiaError("chat completion returned an empty reply")
        return content

    async def complete_draft(self, **kwargs: Any) -> str:
        """Alias so MCP tool names stay explicit; keeps callers readable."""
        return await self.complete(**kwargs)

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int = 1000,
        temperature: float = 0.6,
    ) -> Any:
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message
        except Exception as exc:
            raise NgamiaError(f"chat completion with tools failed: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.close()
