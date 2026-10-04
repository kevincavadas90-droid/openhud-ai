"""Multi-provider LLM layer.

The agent loop speaks one internal message format (OpenAI chat style).
Adapters translate that to each provider:

* ``openai``    - any OpenAI-compatible ``/chat/completions`` endpoint
                  (OpenAI, Groq, Together, DeepSeek, OpenRouter, vLLM ...).
* ``anthropic`` - Anthropic Messages API.
* ``ollama``    - local models via Ollama's OpenAI-compatible endpoint.

No provider is assumed to behave like another: capability flags drive what
the agent is allowed to attempt (notably tool calling).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx


class LLMError(RuntimeError):
    """Raised for configuration or transport problems, with a clear message."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderConfig:
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    supports_tools: bool = True

    @property
    def is_local(self) -> bool:
        return self.provider == "ollama"


DEFAULT_BASE_URLS = {
    "pollinations": "https://text.pollinations.ai/openai",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "ollama": "http://localhost:11434/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "cerebras": "https://api.cerebras.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "github": "https://models.github.ai/inference",
}

# Providers that require no API key at all.
KEYLESS = {"pollinations", "ollama"}


def _normalize_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"_raw": raw}
    return {}


class LLMClient:
    """Synchronous client (the API layer runs it in a thread pool)."""

    def __init__(self, config: ProviderConfig, timeout: float = 180.0) -> None:
        self.config = config
        self.timeout = timeout

    # -- public API ------------------------------------------------------
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        if self.config.provider == "anthropic":
            return self._chat_anthropic(messages, tools)
        return self._chat_openai(messages, tools)

    # -- OpenAI-compatible ----------------------------------------------
    def _chat_openai(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> LLMResponse:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._openai_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools and self.config.supports_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data = self._post(url, headers, payload)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{len(calls)}",
                    name=fn.get("name", ""),
                    arguments=_normalize_tool_arguments(fn.get("arguments")),
                )
            )
        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage=data.get("usage") or {},
        )

    def _openai_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                out.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {
                                    "name": c["name"],
                                    "arguments": json.dumps(c.get("arguments", {})),
                                },
                            }
                            for c in m["tool_calls"]
                        ],
                    }
                )
            elif role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.get("tool_call_id"),
                        "content": m.get("content") or "",
                    }
                )
            else:
                out.append({"role": role, "content": m.get("content") or ""})
        return out

    # -- Anthropic -------------------------------------------------------
    def _chat_anthropic(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> LLMResponse:
        url = self.config.base_url.rstrip("/") + "/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key or "",
            "anthropic-version": "2023-06-01",
        }
        system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
        conv = self._anthropic_messages([m for m in messages if m.get("role") != "system"])
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": conv,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools and self.config.supports_tools:
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]
        data = self._post(url, headers, payload)
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=block.get("id", f"call_{len(calls)}"),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )
        return LLMResponse(
            content="".join(text_parts),
            tool_calls=calls,
            finish_reason=data.get("stop_reason", "stop"),
            usage=data.get("usage") or {},
        )

    def _anthropic_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for c in m["tool_calls"]:
                    blocks.append(
                        {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c.get("arguments", {})}
                    )
                out.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.get("tool_call_id"),
                                "content": m.get("content") or "",
                            }
                        ],
                    }
                )
            else:
                out.append({"role": role, "content": m.get("content") or ""})
        return out

    # -- transport -------------------------------------------------------
    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise LLMError(f"Falha de rede ao chamar {url}: {exc}") from exc
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise LLMError(f"Provedor retornou HTTP {resp.status_code}: {detail}")
        try:
            return resp.json()
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise LLMError("Resposta do provedor não é JSON válido") from exc
