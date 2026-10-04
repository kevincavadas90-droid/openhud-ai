"""Persistent background job queue.

Long-running work (video render, batch image generation, large code
execution) is tracked as a job with an explicit lifecycle:

    QUEUED → RUNNING → (WAITING_PERMISSION | RETRYING) → COMPLETED | FAILED | CANCELLED

Progress and logs are stored so the UI can show *real* progress; nothing is
ever simulated. A single worker thread processes jobs FIFO; a job handler is
a callable ``(job, report) -> dict`` where ``report(progress, message)``
updates the stored state.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


class JobStore:
    def __init__(self, db) -> None:
        self.db = db

    def create(self, kind: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        jid = uuid.uuid4().hex
        now = time.time()
        self.db.execute(
            "INSERT INTO jobs(id, kind, status, progress, params, logs, created_at, updated_at) "
            "VALUES(?, ?, 'QUEUED', 0, ?, '', ?, ?)",
            (jid, kind, json.dumps(params or {}), now, now),
        )
        return self.get(jid)

    def get(self, jid: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM jobs WHERE id=?", (jid,))
        return _decode(dict(row)) if row else None

    def list(self, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if kind:
            rows = self.db.query(
                "SELECT * FROM jobs WHERE kind=? ORDER BY created_at DESC LIMIT ?", (kind, limit)
            )
        else:
            rows = self.db.query("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_decode(dict(r)) for r in rows]

    def update(self, jid: str, **fields: Any) -> None:
        allowed = {"status", "progress", "logs", "result", "error"}
        sets, values = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            values.append(json.dumps(v) if k == "result" else v)
        if not sets:
            return
        sets.append("updated_at=?")
        values.append(time.time())
        values.append(jid)
        self.db.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", values)

    def append_log(self, jid: str, message: str) -> None:
        job = self.get(jid)
        if not job:
            return
        logs = (job.get("logs") or "") + message + "\n"
        self.update(jid, logs=logs[-20000:])

    def cancel(self, jid: str) -> bool:
        job = self.get(jid)
        if not job or job["status"] in TERMINAL:
            return False
        self.update(jid, status="CANCELLED")
        return True


def _decode(job: dict[str, Any]) -> dict[str, Any]:
    for key in ("params", "result"):
        if job.get(key):
            try:
                job[key] = json.loads(job[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return job


class JobQueue:
    """Single-worker FIFO queue with auto-restart of the worker on failure."""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self._handlers: dict[str, Callable[[dict, Callable[[int, str], None]], dict]] = {}
        self._q: list[str] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, kind: str, handler: Callable) -> None:
        self._handlers[kind] = handler

    def submit(self, kind: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        job = self.store.create(kind, params)
        with self._lock:
            self._q.append(job["id"])
        self._wake.set()
        return job

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="openhud-jobs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=5)
            self._wake.clear()
            while True:
                with self._lock:
                    if not self._q:
                        break
                    jid = self._q.pop(0)
                try:
                    self._run(jid)
                except Exception as exc:  # worker must survive a bad job
                    self.store.update(jid, status="FAILED", error=f"{type(exc).__name__}: {exc}")

    def _run(self, jid: str) -> None:
        job = self.store.get(jid)
        if not job or job["status"] == "CANCELLED":
            return
        handler = self._handlers.get(job["kind"])
        if handler is None:
            self.store.update(jid, status="FAILED", error=f"Sem handler para '{job['kind']}'")
            return
        self.store.update(jid, status="RUNNING", progress=0)

        def report(progress: int, message: str = "") -> None:
            self.store.update(jid, progress=max(0, min(100, int(progress))))
            if message:
                self.store.append_log(jid, message)

        result = handler(job, report)
        self.store.update(jid, status="COMPLETED", progress=100, result=result)
