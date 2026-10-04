"""Interactive confirmation broker.

When the agent runs in "supervised" autonomy and wants to use a tool that
requires confirmation, the loop blocks on this broker. The web API resolves
the pending request when the user clicks Approve/Deny.
"""
from __future__ import annotations

import threading
import uuid


class PendingConfirmation:
    def __init__(self, request_id: str, tool: str, arguments: dict) -> None:
        self.request_id = request_id
        self.tool = tool
        self.arguments = arguments
        self.event = threading.Event()
        self.approved = False


class ConfirmationBroker:
    def __init__(self) -> None:
        self._pending: dict[str, PendingConfirmation] = {}
        self._lock = threading.Lock()

    def create(self, tool: str, arguments: dict) -> PendingConfirmation:
        req = PendingConfirmation(uuid.uuid4().hex, tool, arguments)
        with self._lock:
            self._pending[req.request_id] = req
        return req

    def resolve(self, request_id: str, approved: bool) -> bool:
        with self._lock:
            req = self._pending.pop(request_id, None)
        if req is None:
            return False
        req.approved = approved
        req.event.set()
        return True

    def wait(self, req: PendingConfirmation, timeout: float = 300.0) -> bool:
        if req.event.wait(timeout):
            return req.approved
        # Timed out: treat as denied and clean up.
        with self._lock:
            self._pending.pop(req.request_id, None)
        return False

    def list_pending(self) -> list[dict]:
        with self._lock:
            return [
                {"request_id": r.request_id, "tool": r.tool, "arguments": r.arguments}
                for r in self._pending.values()
            ]


broker = ConfirmationBroker()
