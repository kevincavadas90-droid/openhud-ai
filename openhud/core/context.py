"""Context manager: select only what is relevant for a task.

Before each turn the agent assembles a bounded context: relevant memories,
similar past experiences, the active mode/personality guidance and (only when
the task mentions them) PC / MT5 / project hints. This keeps the prompt small
and avoids shipping the whole database to the model.

Everything here is read-only and best-effort; missing subsystems degrade to
empty context rather than raising.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .modes import MODES, resolve_mode
from .personality import Personality, adapt


@dataclass
class TaskContext:
    mode: str
    personality: Personality
    memories: list[dict[str, Any]] = field(default_factory=list)
    experiences: list[dict[str, Any]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    route: dict[str, Any] = field(default_factory=dict)


def build_context(
    db,
    user_text: str,
    *,
    selected_mode: str = "auto",
    personality: Personality | None = None,
    learning=None,
    max_memories: int = 6,
    max_experiences: int = 3,
) -> TaskContext:
    """Assemble a bounded, relevant context for one user turn."""
    mode_key = resolve_mode(selected_mode, user_text)
    persona = personality or Personality()

    # Adaptive personality from stored user preferences (opt-in via persona).
    prefs = _preference_texts(db)
    persona = adapt(persona, prefs)
    persona = persona.apply_bias(MODES[mode_key].personality_bias)

    memories = _safe(lambda: db.search_memories(user_text, limit=max_memories), [])
    experiences = []
    if learning is not None:
        experiences = _safe(lambda: learning.relevant(user_text, limit=max_experiences), [])

    hints = _hints(db, user_text)
    return TaskContext(mode=mode_key, personality=persona, memories=memories,
                       experiences=experiences, hints=hints)


def _preference_texts(db) -> list[str]:
    try:
        rows = db.query(
            "SELECT content FROM memories WHERE tags LIKE '%prefer%' OR tags LIKE '%persona%' "
            "ORDER BY updated_at DESC LIMIT 20"
        )
        return [r["content"] for r in rows]
    except Exception:
        return []


def _hints(db, user_text: str) -> list[str]:
    low = (user_text or "").lower()
    hints: list[str] = []
    if any(k in low for k in ("pc", "computador", "cpu", "ram", "gpu", "processo", "temperatura")):
        hints.append("O pedido pode envolver o PC: use as ferramentas pc_* e só reporte dados medidos.")
    if any(k in low for k in ("mt5", "metatrader", "eurusd", "xauusd", "ativo", "candle", "ordem", "trading")):
        hints.append("O pedido pode envolver o MT5: respeite as permissões e nunca invente dados de mercado.")
    if any(k in low for k in ("projeto", "repositório", "repositorio", "código", "codigo", "arquivo")):
        hints.append("O pedido pode envolver arquivos/projeto: prefira o workspace e mostre o que mudou.")
    return hints


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default
