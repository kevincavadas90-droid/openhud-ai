"""Application runtime: shared singletons and settings resolution.

Builds the database, secret store, tool registry and LLM clients from the
values the user configured through the UI.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..tools import build_default_registry
from .crypto import SecretCipher
from .db import create_database
from .llm import DEFAULT_BASE_URLS, LLMClient, ProviderConfig
from .providers import ProviderManager, build_provider_manager
from .secrets_store import SecretStore

# Defaults target the keyless Pollinations endpoint so OpenHUD works with
# zero configuration and zero cost. The user can switch to a keyed provider
# or a local Ollama model at any time.
DEFAULT_SETTINGS: dict[str, Any] = {
    "provider": "pollinations",
    "model": "openai",
    "base_url": DEFAULT_BASE_URLS["pollinations"],
    "temperature": 0.7,
    "max_tokens": 4096,
    "autonomy": "supervised",  # supervised | autonomous
    "allow_network": True,
    "supports_tools": True,
    "enabled_tools": [],  # empty = all
    "max_steps": settings.max_agent_steps,
    "language": "pt-BR",
}

# Keyed providers, in fallback preference order. Each entry describes how to
# build a client when a matching secret is present.
KEYED_PROVIDERS: dict[str, dict[str, Any]] = {
    "groq": {
        "base_url": DEFAULT_BASE_URLS["groq"],
        "model": "llama-3.3-70b-versatile",
        "supports_tools": True,
    },
    "google": {
        "base_url": DEFAULT_BASE_URLS["google"],
        "model": "gemini-2.0-flash",
        "supports_tools": True,
    },
    "openrouter": {
        "base_url": DEFAULT_BASE_URLS["openrouter"],
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "supports_tools": True,
    },
    "openai": {
        "base_url": DEFAULT_BASE_URLS["openai"],
        "model": "gpt-4o-mini",
        "supports_tools": True,
    },
    "anthropic": {
        "base_url": DEFAULT_BASE_URLS["anthropic"],
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-latest",
        "supports_tools": True,
    },
    "deepseek": {
        "base_url": DEFAULT_BASE_URLS["deepseek"],
        "model": "deepseek-chat",
        "supports_tools": True,
    },
    "cerebras": {
        "base_url": DEFAULT_BASE_URLS["cerebras"],
        "model": "llama-3.3-70b",
        "supports_tools": True,
    },
    "mistral": {
        "base_url": DEFAULT_BASE_URLS["mistral"],
        "model": "mistral-large-latest",
        "supports_tools": True,
    },
    "github": {
        "base_url": DEFAULT_BASE_URLS["github"],
        "model": "openai/gpt-4o-mini",
        "supports_tools": True,
    },
}


class Runtime:
    def __init__(self) -> None:
        self.db = create_database(settings.db_path, settings.database_url)
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
        provider = s.get("provider", "pollinations")
        api_key = self.secrets.get(provider)
        base_url = s.get("base_url") or DEFAULT_BASE_URLS.get(provider, DEFAULT_BASE_URLS["pollinations"])
        return ProviderConfig(
            provider="anthropic" if provider == "anthropic" else ("ollama" if provider == "ollama" else "openai"),
            model=s.get("model", "openai"),
            base_url=base_url,
            api_key=api_key,
            temperature=float(s.get("temperature", 0.7)),
            max_tokens=int(s.get("max_tokens", 4096)),
            supports_tools=bool(s.get("supports_tools", True)),
        )

    def llm_client(self) -> LLMClient:
        return LLMClient(self.provider_config())

    def provider_manager(self) -> ProviderManager:
        """Build a fresh fallback chain from the current settings and keys.

        Built per turn so that newly added keys or a changed provider take
        effect immediately without a restart.
        """
        s = self.get_settings()
        provider = s.get("provider", "pollinations")
        return build_provider_manager(
            selected_provider=provider,
            model=s.get("model", "openai"),
            base_url=s.get("base_url") or DEFAULT_BASE_URLS.get(provider, DEFAULT_BASE_URLS["pollinations"]),
            temperature=float(s.get("temperature", 0.7)),
            max_tokens=int(s.get("max_tokens", 4096)),
            supports_tools=bool(s.get("supports_tools", True)),
            secret_lookup=self.secrets.get,
            keyed_defaults=KEYED_PROVIDERS,
        )


runtime = Runtime()
