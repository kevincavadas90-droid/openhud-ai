"""Background scheduler for recurring agent tasks.

A daemon thread wakes periodically and runs any due task in a fresh
conversation. Tasks always run in autonomous mode so they can complete
unattended, but the same destructive-command guardrails still apply.
"""
from __future__ import annotations

import threading
import time

from ..core.runtime import Runtime, runtime as default_runtime
from .loop import Agent


class Scheduler:
    def __init__(self, runtime: Runtime, poll_seconds: int = 15) -> None:
        self.runtime = runtime
        self.poll_seconds = poll_seconds
        self.agent = Agent(runtime)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="openhud-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                for task in self.runtime.db.due_tasks(time.time()):
                    with self._lock:
                        if task["id"] in self._running:
                            continue
                        self._running.add(task["id"])
                    threading.Thread(target=self._run_task, args=(task,), daemon=True).start()
            except Exception as exc:  # never let the scheduler die
                self.runtime.db.add_activity("scheduler_error", str(exc))

    def _run_task(self, task: dict) -> None:
        tid = task["id"]
        db = self.runtime.db
        try:
            conv = db.create_conversation(title=f"[tarefa] {task['name']}")
            db.add_activity("task_start", f"{task['name']}: {task['prompt']}", conv["id"])
            collected: list[str] = []
            for ev in self.agent.run(conv["id"], task["prompt"]):
                if ev.type == "token":
                    collected.append(ev.data.get("text", ""))
                elif ev.type == "error":
                    collected.append(f"[erro] {ev.data.get('message')}")
            result = "\n".join(collected).strip() or "(sem resultado)"
            db.record_task_run(tid, "ok", result)
            db.add_activity("task_done", f"{task['name']} concluída", conv["id"])
        except Exception as exc:
            db.record_task_run(tid, "error", str(exc))
            db.add_activity("task_error", f"{task['name']}: {exc}")
        finally:
            with self._lock:
                self._running.discard(tid)


scheduler = Scheduler(default_runtime)
