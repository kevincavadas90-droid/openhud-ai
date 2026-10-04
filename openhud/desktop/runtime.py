"""Background agent runtime for the desktop app.

Runs the existing :class:`AgentClient` in its own asyncio event loop on a
daemon thread so the tray/GUI stays responsive and can start, stop and report
the connection state without touching the network code. This module has no GUI
dependencies, so it is fully testable on Linux/CI.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable

from .config import DesktopConfig


class AgentRuntime:
    def __init__(self, config: DesktopConfig,
                 on_state: Callable[[str, str], None] | None = None) -> None:
        self.config = config
        self._on_state = on_state
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None
        self._client = None
        self.state = "disconnected"
        self.last_error = ""

    # -- state -----------------------------------------------------------
    def _set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        if detail:
            self.last_error = detail
        if self._on_state:
            try:
                self._on_state(state, detail)
            except Exception:  # noqa: BLE001
                pass

    def status_label(self) -> str:
        return {
            "connected": "OpenHUD conectado",
            "connecting": "OpenHUD conectando…",
            "error": "OpenHUD desconectado (erro)",
            "disconnected": "OpenHUD desconectado",
        }.get(self.state, "OpenHUD desconectado")

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- lifecycle -------------------------------------------------------
    def start(self) -> bool:
        if self.is_running():
            return True
        if not self.config.server:
            self._set_state("disconnected", "Servidor não configurado.")
            return False
        if not self.config.token and not self.config.extra.get("pair_code"):
            self._set_state("disconnected", "Sem token: faça o pareamento primeiro.")
            return False

        from openhud.agent.agent_client import AgentClient

        def _runner() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._client = AgentClient(
                self.config.server,
                self.config.token or None,
                self.config.extra.get("pair_code"),
                self.config.name or "Meu PC",
                on_state=self._set_state,
            )
            self._task = self._loop.create_task(self._client.run_forever())
            try:
                self._loop.run_until_complete(self._task)
            except Exception as exc:  # noqa: BLE001
                self._set_state("error", f"{type(exc).__name__}: {exc}")
            finally:
                try:
                    self._loop.close()
                except Exception:  # noqa: BLE001
                    pass

        self._set_state("connecting")
        self._thread = threading.Thread(target=_runner, daemon=True, name="openhud-agent")
        self._thread.start()
        return True

    def stop(self) -> None:
        loop = self._loop
        task = self._task
        if loop and task:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except Exception:  # noqa: BLE001
                pass
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self._loop = None
        self._task = None
        self._client = None
        self._set_state("disconnected")

    def reconnect(self) -> bool:
        self.stop()
        return self.start()

    def permissions_payload(self) -> dict[str, Any]:
        return self.config.permissions()
