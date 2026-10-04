"""Tiny in-memory rate limiter.

Protects the login endpoint against brute force and the chat endpoint against
runaway clients. It is intentionally simple: a fixed window per client key
(IP address). For a single-operator deployment this is sufficient, and it
adds no external dependency.
"""
from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def retry_after(self, key: str) -> int:
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if not hits:
            return 0
        return max(0, int(self.window - (now - min(hits))))


login_limiter = RateLimiter(limit=8, window_seconds=300)   # 8 tentativas / 5 min
chat_limiter = RateLimiter(limit=30, window_seconds=60)    # 30 mensagens / min
# Account flows get their own windows so a burst on one endpoint cannot lock
# the others.
register_limiter = RateLimiter(limit=6, window_seconds=3600)   # 6 contas / hora / IP
reset_limiter = RateLimiter(limit=6, window_seconds=900)       # 6 pedidos / 15 min / IP
account_limiter = RateLimiter(limit=20, window_seconds=300)    # mutações / 5 min / IP
