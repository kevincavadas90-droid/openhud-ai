"""Application runtime: shared singletons and settings resolution.

Builds the database, secret store, tool registry and LLM clients from the
values the user configured through the UI.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..tools import build_default_registry
from .crypto import SecretCipher
from .db import Database
from .llm import DEFAULT_BASE_URLS, LLMClient, ProviderConfig
from .secrets_store import SecretStore

DEFAULT_SETTINGS: dict[str, Any] = {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "base_url": DEFAULT_BASE_URLS["openai"],
    "temperature": 0.7,
    "max_tokens": 4096,
    "autonomy": "supervised",  # supervised | autonomous
    "allow_network": True,
    "supports_tools": True,
    "enabled_tools": [],  # empty = all
    "max_steps": settings.max_agent_steps,
    "language": "pt-BR",
}


class Runtime:
    def __init__(self) -> None:
        self.db = Database(settings.db_path)
        self.cipher = SecretCipher(settings.key_path)
        self.secrets = SecretStore(self.db, self.cipher)
        self.registry = build_default_registry()
        self._apply_defaults()

    def _apply_defaults(self) -> None:
        for key, value in DEFAULT_SETTINGS.items():
            if self.db.get_setting(key) is None:
                self.db.set_setting(key, value)

    # -- settings --------------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        merged = dict(DEFAULT_SETTINGS)
        merged.update(self.db.all_settings())
        return merged

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_SETTINGS)
        for key, value in patch.items():
            if key in allowed:
                self.db.set_setting(key, value)
        return self.get_settings()

    # -- tool selection --------------------------------------------------
    def enabled_tool_names(self) -> set[str] | None:
        enabled = self.db.get_setting("enabled_tools") or []
        if not enabled:
            return None
        return set(enabled)

    def tool_summaries(self) -> list[str]:
        enabled = self.enabled_tool_names()
        return [
            f"{t.name}: {t.description}"
            for t in self.registry.all()
            if enabled is None or t.name in enabled
        ]

    # -- LLM -------------------------------------------------------------
    def provider_config(self) -> ProviderConfig:
        s = self.get_settings()
        provider = s.get("provider", "openai")
        key_name = {"openai": "openai", "anthropic": "anthropic",
                    "groq": "groq", "deepseek": "deepseek",
                    "openrouter": "openrouter", "ollama": "ollama"}.get(provider, provider)
        api_key = self.secrets.get(key_name)
        base_url = s.get("base_url") or DEFAULT_BASE_URLS.get(provider, DEFAULT_BASE_URLS["openai"])
        return ProviderConfig(
            provider=provider,
            model=s.get("model", "gpt-4o-mini"),
            base_url=base_url,
            api_key=api_key,
            temperature=float(s.get("temperature", 0.7)),
            max_tokens=int(s.get("max_tokens", 4096)),
            supports_tools=bool(s.get("supports_tools", True)),
        )

    def llm_client(self) -> LLMClient:
        return LLMClient(self.provider_config())


runtime = Runtime()
