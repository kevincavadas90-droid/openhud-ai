"""Continuous learning from outcomes.

This is *not* model training. It records experiences (action → context →
result → feedback) in the database and surfaces similar past experiences so
the agent can reuse what worked and avoid what failed. The distinction is
stated plainly so nothing is over-claimed.

Memory tiers:
* short_term  — the current conversation window (handled by the DB messages);
* long_term   — explicit ``memories`` the user curates;
* episodic    — concrete experiences with an outcome (this module);
* semantic    — stable facts/preferences (``memories`` tagged ``semantic``).
"""
from __future__ import annotations

import time
import uuid
from typing import Any

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "a", "o", "as", "os", "e", "que", "em",
    "um", "uma", "para", "com", "no", "na", "por", "se", "the", "of", "to",
}


def _keywords(text: str) -> set[str]:
    words = re_findall(text)
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def re_findall(text: str) -> list[str]:
    import re

    return re.findall(r"[a-zà-ÿ0-9]+", (text or "").lower())


class LearningStore:
    """Persistence for episodic experiences."""

    def __init__(self, db) -> None:
        self.db = db

    def record(
        self,
        action: str,
        context: str,
        result: str,
        success: bool,
        feedback: str = "",
        tags: str = "",
    ) -> dict[str, Any]:
        exp = {
            "id": uuid.uuid4().hex,
            "action": action[:500],
            "context": context[:4000],
            "result": result[:4000],
            "success": 1 if success else 0,
            "feedback": feedback[:2000],
            "tags": tags[:300],
            "created_at": time.time(),
        }
        self.db.execute(
            "INSERT INTO experiences(id, action, context, result, success, feedback, tags, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (exp["id"], exp["action"], exp["context"], exp["result"], exp["success"],
             exp["feedback"], exp["tags"], exp["created_at"]),
        )
        return exp

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM experiences ORDER BY created_at DESC LIMIT ?", (limit,)
        )]

    def relevant(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return past experiences that share keywords with ``query``."""
        wanted = _keywords(query)
        if not wanted:
            return []
        scored: list[tuple[int, dict[str, Any]]] = []
        for exp in self.list(limit=500):
            hay = _keywords(f"{exp['action']} {exp['context']} {exp['tags']}")
            score = len(wanted & hay)
            if score:
                scored.append((score, exp))
        scored.sort(key=lambda p: (p[0], p[1]["created_at"]), reverse=True)
        return [e for _, e in scored[:limit]]

    def stats(self) -> dict[str, Any]:
        rows = self.db.query("SELECT success, COUNT(*) AS n FROM experiences GROUP BY success")
        counts = {int(r["success"]): int(r["n"]) for r in rows}
        ok, bad = counts.get(1, 0), counts.get(0, 0)
        total = ok + bad
        return {
            "total": total,
            "success": ok,
            "failure": bad,
            "success_rate": round(ok / total * 100, 1) if total else None,
        }
