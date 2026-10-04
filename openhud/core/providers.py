"""Provider fallback manager.

OpenHUD must keep answering even when a single free provider is rate
limited or down. The manager holds an ordered chain of providers and tries
them in order, remembering which one last succeeded so healthy providers are
reused. Every attempt is reported so the UI can show which model answered and
why a provider was skipped.

Providers are described declaratively; each one is either keyless (e.g. the
public Pollinations endpoint) or keyed (Groq, OpenRouter, OpenAI, ...). No
provider is abused: when a provider reports a rate limit or auth failure we
move on instead of retrying aggressively.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .llm import LLMClient, LLMError, ProviderConfig

# Providers that work with no API key at all. Kept minimal and legitimate.
KEYLESS_PROVIDERS: dict[str, dict[str, Any]] = {
    "pollinations": {
        "base_url": "https://text.pollinations.ai/openai",
        "model": "openai",
        "supports_tools": False,
        "timeout": 90.0,
        "label": "Pollinations (gpt-oss-20b, sem chave)",
    },
}

# Cooldown after a provider fails, so a dead provider is not retried on every
# single call but is still probed again after a while.
FAILURE_COOLDOWN_SECONDS = 60.0

# Transient failures (5xx, network hiccups) are retried a couple of times with
# a short backoff before the provider is skipped for this turn. Rate limits
# (429/402) are not hammered: they move straight to the next provider.
TRANSIENT_RETRIES = 2
TRANSIENT_BACKOFF_SECONDS = 0.8


def _is_transient(detail: str) -> bool:
    return ("HTTP 5" in detail) or ("Falha de rede" in detail)


@dataclass
class ProviderEntry:
    name: str
    config: ProviderConfig
    label: str
    priority: int
    timeout: float = 180.0
    healthy: bool = True
    failures: int = 0
    last_error: str | None = None
    last_failure_at: float = 0.0

    def cooldown_active(self, now: float) -> bool:
        if self.healthy:
            return False
        return (now - self.last_failure_at) < FAILURE_COOLDOWN_SECONDS


@dataclass
class Attempt:
    provider: str
    ok: bool
    detail: str = ""


@dataclass
class ChatOutcome:
    response: Any
    provider: str
    label: str
    attempts: list[Attempt] = field(default_factory=list)


class AllProvidersFailed(LLMError):
    """Raised when every provider in the chain failed."""

    def __init__(self, attempts: list[Attempt]) -> None:
        self.attempts = attempts
        lines = ["Todos os provedores de IA falharam:"]
        for a in attempts:
            lines.append(f"  - {a.provider}: {a.detail}")
        lines.append(
            "Configure uma chave de API em Configurações (ex.: Groq, OpenRouter) "
            "ou rode um modelo local com Ollama."
        )
        super().__init__("\n".join(lines))


class ProviderManager:
    def __init__(self, entries: list[ProviderEntry]) -> None:
        self._entries = sorted(entries, key=lambda e: e.priority)
        self._lock = threading.Lock()
        self._last_good: str | None = None

    # -- introspection ---------------------------------------------------
    def entries(self) -> list[ProviderEntry]:
        return list(self._entries)

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": e.name,
                "label": e.label,
                "priority": e.priority,
                "healthy": e.healthy,
                "failures": e.failures,
                "last_error": e.last_error,
            }
            for e in self._entries
        ]

    def primary(self) -> ProviderEntry:
        return self._entries[0]

    # -- execution -------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_attempt: Callable[[Attempt], None] | None = None,
    ) -> ChatOutcome:
        attempts: list[Attempt] = []
        for entry in self._ordered(time.time()):
            # A provider that does not support tools is still usable for a
            # plain answer; we simply withhold the tool specs from it.
            effective_tools = tools if entry.config.supports_tools else None
            detail = ""
            response = None
            for try_index in range(TRANSIENT_RETRIES + 1):
                try:
                    client = LLMClient(entry.config, timeout=entry.timeout)
                    response = client.chat(messages, tools=effective_tools)
                    break
                except LLMError as exc:
                    detail = str(exc)
                    if try_index < TRANSIENT_RETRIES and _is_transient(detail):
                        time.sleep(TRANSIENT_BACKOFF_SECONDS * (try_index + 1))
                        continue
                    break
            if response is None:
                self._mark_failure(entry, detail)
                attempt = Attempt(entry.name, False, detail)
                attempts.append(attempt)
                if on_attempt:
                    on_attempt(attempt)
                continue
            self._mark_success(entry)
            attempt = Attempt(entry.name, True, entry.label)
            attempts.append(attempt)
            if on_attempt:
                on_attempt(attempt)
            return ChatOutcome(response, entry.name, entry.label, attempts)

        raise AllProvidersFailed(attempts)

    def _ordered(self, now: float) -> list[ProviderEntry]:
        healthy = [e for e in self._entries if not e.cooldown_active(now)]
        cooling = [e for e in self._entries if e.cooldown_active(now)]
        # Prefer the last provider that worked, then priority order.
        with self._lock:
            last = self._last_good
        healthy.sort(key=lambda e: (0 if e.name == last else 1, e.priority))
        return healthy + cooling

    def _mark_success(self, entry: ProviderEntry) -> None:
        entry.healthy = True
        entry.failures = 0
        entry.last_error = None
        with self._lock:
            self._last_good = entry.name

    def _mark_failure(self, entry: ProviderEntry, detail: str) -> None:
        entry.healthy = False
        entry.failures += 1
        entry.last_error = detail[:300]
        entry.last_failure_at = time.time()


def build_provider_manager(
    selected_provider: str,
    model: str,
    base_url: str,
    temperature: float,
    max_tokens: int,
    supports_tools: bool,
    secret_lookup: Callable[[str], str | None],
    keyed_defaults: dict[str, dict[str, Any]],
    keyless_order: list[str] | None = None,
) -> ProviderManager:
    """Assemble the fallback chain for the current configuration.

    Order: the user's explicitly selected provider first, then any other
    configured keyed providers, then the keyless public providers, then a
    local Ollama instance as a last resort.
    """
    entries: list[ProviderEntry] = []
    priority = 0

    def add_keyed(name: str, cfg: dict[str, Any], prio: int, override: bool = False) -> None:
        key = secret_lookup(name)
        if not key:
            return
        chosen_model = model if override else cfg["model"]
        chosen_url = base_url if override else cfg["base_url"]
        entries.append(
            ProviderEntry(
                name=name,
                label=f"{name} · {chosen_model}",
                config=ProviderConfig(
                    provider=cfg.get("provider", name),
                    model=chosen_model,
                    base_url=chosen_url,
                    api_key=key,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    supports_tools=cfg.get("supports_tools", supports_tools),
                ),
                priority=prio,
                timeout=cfg.get("timeout", 180.0),
            )
        )

    def add_keyless(name: str, prio: int) -> None:
        kp = KEYLESS_PROVIDERS[name]
        entries.append(
            ProviderEntry(
                name=name,
                label=kp["label"],
                config=ProviderConfig(
                    provider="openai",
                    model=kp["model"],
                    base_url=kp["base_url"],
                    api_key=None,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    supports_tools=kp.get("supports_tools", False),
                ),
                priority=prio,
                timeout=kp.get("timeout", 90.0),
            )
        )

    # 1. The selected provider, if usable. The user's base_url/model win here.
    if selected_provider in keyed_defaults:
        add_keyed(selected_provider, keyed_defaults[selected_provider], priority, override=True)
        priority += 1
    elif selected_provider in KEYLESS_PROVIDERS:
        add_keyless(selected_provider, priority)
        priority += 1
    elif selected_provider == "ollama":
        entries.append(
            ProviderEntry(
                name="ollama",
                label=f"ollama · {model}",
                config=ProviderConfig(
                    provider="ollama", model=model, base_url=base_url,
                    api_key=None, temperature=temperature, max_tokens=max_tokens,
                    supports_tools=supports_tools,
                ),
                priority=priority, timeout=300.0,
            )
        )
        priority += 1

    # 2. Any other keyed provider that has a key.
    for name, cfg in keyed_defaults.items():
        if name == selected_provider:
            continue
        add_keyed(name, cfg, priority)
        priority += 1

    # 3. Keyless public providers.
    for name in (keyless_order or list(KEYLESS_PROVIDERS)):
        if name == selected_provider:
            continue
        if name in KEYLESS_PROVIDERS:
            add_keyless(name, priority)
            priority += 1

    # 4. Local Ollama as the final fallback.
    if selected_provider != "ollama":
        entries.append(
            ProviderEntry(
                name="ollama",
                label=f"ollama (local) · {model}",
                config=ProviderConfig(
                    provider="ollama", model=model, base_url="http://localhost:11434/v1",
                    api_key=None, temperature=temperature, max_tokens=max_tokens,
                    supports_tools=supports_tools,
                ),
                priority=priority, timeout=20.0,
            )
        )

    if not entries:
        add_keyless("pollinations", 0)

    return ProviderManager(entries)
