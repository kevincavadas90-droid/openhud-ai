"""Intelligent model router.

Maps a resolved mode to a task family and exposes the routing decision so the
UI and the agent can show *why* a model was chosen. The actual provider
fallback (trying each configured provider, then the keyless/local ones) stays
in :mod:`openhud.core.providers`; the router only picks the preferred family
and any model hint.

Media families (image/video/voice) are not chat providers: the router reports
them so the caller dispatches to the matching service instead of the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass

# Model suggestions per family. These are hints only; the user's configured
# model always wins (important: local tests depend on the configured model).
FAMILY_HINTS: dict[str, list[str]] = {
    "fast": ["llama-3.1-8b-instant", "gpt-4o-mini", "gemini-2.0-flash"],
    "reason": ["deepseek-reasoner", "claude-3-5-sonnet-latest", "gemini-2.5-pro"],
    "code": ["deepseek-chat", "claude-3-5-sonnet-latest", "gpt-4o"],
    "creative": ["mistral-large-latest", "gpt-4o"],
    "vision": [],  # handled by media services, not the chat LLM
}

FAMILY_LABEL = {
    "fast": "modelo rápido",
    "reason": "modelo de raciocínio",
    "code": "modelo de código",
    "creative": "modelo criativo",
    "vision": "provider de mídia",
}


@dataclass
class Route:
    family: str
    reason: str
    model_hint: str | None = None

    def to_dict(self) -> dict:
        return {"family": self.family, "reason": self.reason, "model_hint": self.model_hint}


def route(mode_key: str, family: str, configured_model: str) -> Route:
    """Build a routing decision for a resolved mode.

    The configured model is kept as the effective model; the hint is only a
    suggestion surfaced in diagnostics.
    """
    hint = (FAMILY_HINTS.get(family) or [None])[0]
    reason = f"modo {mode_key} → {FAMILY_LABEL.get(family, family)}"
    return Route(family=family, reason=reason, model_hint=hint)
