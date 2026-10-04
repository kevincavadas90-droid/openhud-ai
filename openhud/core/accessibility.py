"""Accessibility preferences (Part 2).

A small, persisted set of UI/voice preferences used by the beginner and
accessibility profiles: larger text, big buttons, high contrast, calm voice and
read-aloud. Stored as settings so both the SPA and the agent can honour them.
"""
from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "large_text": False,
    "big_buttons": False,
    "high_contrast": False,
    "read_aloud": False,
    "calm_voice": False,
    "simple_language": False,
}

_LABELS = {
    "large_text": "Texto maior",
    "big_buttons": "Botões grandes",
    "high_contrast": "Alto contraste",
    "read_aloud": "Ler em voz alta",
    "calm_voice": "Voz mais calma",
    "simple_language": "Linguagem simples",
}


def from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    raw = settings.get("accessibility") or {}
    return {**DEFAULTS, **{k: bool(v) for k, v in raw.items() if k in DEFAULTS}}


def merge(settings: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    current = from_settings(settings)
    for k, v in (patch or {}).items():
        if k in DEFAULTS:
            current[k] = bool(v)
    return current


def labels() -> dict[str, str]:
    return dict(_LABELS)
