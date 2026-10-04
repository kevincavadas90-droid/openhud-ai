"""Agent hub: pairing, authentication and live control of PC agents.

The web site never talks to the user's computer directly. The OpenHUD Agent
installed on the PC opens a single outbound WebSocket to this hub, authenticates
with a device token, and then streams metrics and receives commands. This module
owns the device registry (persisted), the pairing-code flow, the live connection
registry and the request/response plumbing used to send commands to an agent.

Security model:
  * Pairing uses a short, single-use, time-limited code that the user reads from
    the site and types into the agent. Only an authenticated site session can
    mint a code.
  * The long-lived device token is returned to the agent exactly once; the hub
    stores only its SHA-256 hash. Tokens can be revoked at any time.
  * Agents authenticate as the first WebSocket message, so the token never
    appears in a URL, proxy log or Referer header.
  * Every command is scoped by the device's granted permissions, checked here
    before it is forwarded to the agent.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from ..trading.core import DEFAULT_TRADING_PERMISSIONS, TRADING_PERMISSION_KEYS

PAIRING_TTL_SECONDS = 600.0
DEVICE_OFFLINE_AFTER = 15.0  # seconds without a heartbeat before "offline"

# Permission keys the agent understands. "commands" gates arbitrary shell
# execution; everything else gates a read-only metric family. Trading keys are
# appended so the same permission store governs MT5 access.
PERMISSION_KEYS = [
    "system",
    "cpu",
    "gpu",
    "ram",
    "storage",
    "processes",
    "temperatures",
    "network",
    "games",
    "commands",
    "screen",     # screen capture + OCR analysis
    "control",    # mouse/keyboard/window control
    "voice",      # microphone / audio
] + TRADING_PERMISSION_KEYS

DEFAULT_PERMISSIONS = {
    "system": True,
    "cpu": True,
    "gpu": True,
    "ram": True,
    "storage": True,
    "processes": False,
    "temperatures": True,
    "network": False,
    "games": False,
    "commands": False,
    # Screen/control/voice are powerful: off until the user explicitly enables them.
    "screen": False,
    "control": False,
    "voice": False,
    **DEFAULT_TRADING_PERMISSIONS,
}

# Commands that require the "commands" permission.
COMMAND_PERMISSION = {
    "shell": "commands",
    "run_command": "commands",
    "kill_process": "processes",
    "set_permission": None,
    "get_metrics": None,
    "list_processes": "processes",
    "diagnose": None,
    "scan_games": "games",
    "ping": None,
    # Screen vision (read-only of the user's own screen).
    "screen_capture": "screen",
    "screen_analyze": "screen",
    "screen_find": "screen",
    "screen_highlight": "screen",
    "window_list": "screen",
    # Input control.
    "mouse_move": "control",
    "mouse_click": "control",
    "mouse_double_click": "control",
    "mouse_scroll": "control",
    "keyboard_type": "control",
    "keyboard_press": "control",
    "open_application": "control",
    "open_url": "control",
    "window_focus": "control",
    "window_close": "control",
    # MT5 / trading commands (spec items 45-56). Read commands need
    # ALLOW_MARKET_READ; order submission is gated per mode below.
    "mt5_status": "ALLOW_MARKET_READ",
    "mt5_account": "ALLOW_MARKET_READ",
    "mt5_symbol": "ALLOW_MARKET_READ",
    "mt5_rates": "ALLOW_MARKET_READ",
    "mt5_positions": "ALLOW_MARKET_READ",
    "mt5_orders": "ALLOW_MARKET_READ",
    "mt5_send_order": "ALLOW_DEMO_TRADING",  # refined by mode in request()
    "mt5_close_position": "ALLOW_ORDER_CLOSE",
}


def _now() -> float:
    return time.time()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Device:
    id: str
    name: str
    platform: str
    token_hash: str
    created_at: float
    last_seen: float = 0.0
    info: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_PERMISSIONS))
    metrics: dict[str, Any] = field(default_factory=dict)
    metrics_at: float = 0.0
    # Trading state lives with the device that holds the MT5 terminal.
    trading_mode: str = "analysis"  # learn | analysis | simulation | demo | real
    risk_limits: dict[str, Any] = field(default_factory=dict)
    emergency_stop: bool = False
    mt5_status: dict[str, Any] = field(default_factory=dict)

    def online(self) -> bool:
        return (_now() - self.last_seen) < DEVICE_OFFLINE_AFTER

    def public(self) -> dict[str, Any]:
        """Representation safe to send to the browser (no token material)."""
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "online": self.online(),
            "info": self.info,
            "permissions": self.permissions,
            "metrics": self.metrics,
            "metrics_at": self.metrics_at,
            "trading_mode": self.trading_mode,
            "risk_limits": self.risk_limits,
            "emergency_stop": self.emergency_stop,
            "mt5_status": self.mt5_status,
        }


class AgentHub:
    """Registry of devices plus their live WebSocket connections."""

    def __init__(self, db) -> None:
        self.db = db
        self._devices: dict[str, Device] = {}
        self._pairing: dict[str, dict[str, Any]] = {}
        self._connections: dict[str, Any] = {}  # device_id -> websocket
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = threading.RLock()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.on_change: Callable[[str], None] | None = None
        self._load()

    # -- persistence -----------------------------------------------------
    def _load(self) -> None:
        raw = self.db.get_setting("agent_devices") or []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = []
        for item in raw:
            try:
                dev = Device(**item)
            except TypeError:
                continue
            # Backfill permissions added after this device was saved (e.g. the
            # MT5 permission keys) so the defaults stay consistent.
            for key, value in DEFAULT_PERMISSIONS.items():
                dev.permissions.setdefault(key, value)
            self._devices[dev.id] = dev

    def _save(self) -> None:
        self.db.set_setting("agent_devices", [asdict(d) for d in self._devices.values()])

    # -- pairing ---------------------------------------------------------
    def create_pairing_code(self) -> dict[str, Any]:
        code = f"{secrets.randbelow(10**6):06d}"
        with self._lock:
            self._pairing[code] = {"created_at": _now(), "used": False}
            # prune expired codes
            for c, meta in list(self._pairing.items()):
                if _now() - meta["created_at"] > PAIRING_TTL_SECONDS:
                    self._pairing.pop(c, None)
        return {"code": code, "expires_in": int(PAIRING_TTL_SECONDS)}

    def redeem_pairing_code(self, code: str, name: str, platform: str, info: dict[str, Any]) -> dict[str, Any]:
        code = (code or "").strip()
        with self._lock:
            meta = self._pairing.get(code)
            if not meta or meta["used"] or (_now() - meta["created_at"]) > PAIRING_TTL_SECONDS:
                raise ValueError("Código de pareamento inválido ou expirado.")
            meta["used"] = True
            token = secrets.token_urlsafe(32)
            dev = Device(
                id=uuid.uuid4().hex[:16],
                name=(name or "Meu PC")[:64],
                platform=(platform or "unknown")[:32],
                token_hash=_hash_token(token),
                created_at=_now(),
                last_seen=_now(),
                info=info or {},
            )
            self._devices[dev.id] = dev
            self._save()
        return {"device_id": dev.id, "token": token, "name": dev.name}

    # -- device management ----------------------------------------------
    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [d.public() for d in sorted(self._devices.values(), key=lambda x: x.created_at)]

    def get_device(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    def verify_token(self, token: str) -> Device | None:
        if not token:
            return None
        h = _hash_token(token)
        with self._lock:
            for dev in self._devices.values():
                if secrets.compare_digest(dev.token_hash, h):
                    return dev
        return None

    def set_permissions(self, device_id: str, permissions: dict[str, bool]) -> dict[str, Any]:
        dev = self._devices.get(device_id)
        if not dev:
            raise KeyError("Dispositivo não encontrado.")
        merged = dict(dev.permissions)
        for k, v in (permissions or {}).items():
            if k in PERMISSION_KEYS:
                merged[k] = bool(v)
        # Real trading can only be enabled when explicitly requested; never
        # implied by a generic permission update.
        dev.permissions = merged
        self._save()
        self._notify("permissions", dev.id)
        self.send(dev.id, {"type": "permissions", "permissions": merged})
        return dev.public()

    # -- trading state (lives with the device that runs MT5) -------------
    def set_trading_mode(self, device_id: str, mode: str) -> dict[str, Any]:
        from ..trading.core import MODES, MODES_REQUIRING_PERMISSION

        dev = self._devices.get(device_id)
        if not dev:
            raise KeyError("Dispositivo não encontrado.")
        if mode not in MODES:
            raise ValueError(f"Modo inválido: {mode}")
        perm = MODES_REQUIRING_PERMISSION.get(mode)
        if perm and not dev.permissions.get(perm, False):
            raise PermissionError(f"O modo '{mode}' exige a permissão {perm}, que está desativada.")
        dev.trading_mode = mode
        self._save()
        self._notify("trading", dev.id)
        return dev.public()

    def set_risk_limits(self, device_id: str, limits: dict[str, Any]) -> dict[str, Any]:
        from ..trading.core import RiskLimits

        dev = self._devices.get(device_id)
        if not dev:
            raise KeyError("Dispositivo não encontrado.")
        dev.risk_limits = RiskLimits.from_dict(limits).to_dict()
        self._save()
        self._notify("trading", dev.id)
        return dev.public()

    def set_emergency_stop(self, device_id: str, active: bool) -> dict[str, Any]:
        dev = self._devices.get(device_id)
        if not dev:
            raise KeyError("Dispositivo não encontrado.")
        dev.emergency_stop = bool(active)
        self._save()
        self._notify("trading", dev.id)
        return dev.public()

    def record_mt5_status(self, device_id: str, status: dict[str, Any]) -> None:
        dev = self._devices.get(device_id)
        if dev:
            dev.mt5_status = status or {}
            self._notify("trading", device_id)

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            dev = self._devices.pop(device_id, None)
            self._connections.pop(device_id, None)
        if dev:
            self._save()
            self._notify("revoked", device_id)
            return True
        return False

    # -- live connections -----------------------------------------------
    def attach(self, device: Device, ws) -> None:
        with self._lock:
            self._connections[device.id] = ws
        device.last_seen = _now()
        self._notify("online", device.id)

    def detach(self, device_id: str) -> None:
        with self._lock:
            self._connections.pop(device_id, None)
        self._notify("offline", device_id)

    def is_connected(self, device_id: str) -> bool:
        return device_id in self._connections

    def touch(self, device_id: str, metrics: dict[str, Any] | None = None) -> None:
        dev = self._devices.get(device_id)
        if not dev:
            return
        dev.last_seen = _now()
        if metrics is not None:
            dev.metrics = metrics
            dev.metrics_at = _now()
        self._notify("metrics", device_id)

    def send(self, device_id: str, message: dict[str, Any]) -> bool:
        """Send a JSON message to a connected agent (thread-safe)."""
        ws = self._connections.get(device_id)
        if ws is None or self.loop is None:
            return False
        try:
            asyncio.run_coroutine_threadsafe(
                ws.send_text(json.dumps(message, ensure_ascii=False)), self.loop
            )
            return True
        except Exception:
            return False

    def request(self, device_id: str, command: str, args: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
        """Send a command and block for its result (called from worker threads).

        Raises ``TimeoutError``/``RuntimeError`` so the API layer can surface a
        real error instead of hanging.
        """
        dev = self._devices.get(device_id)
        if not dev:
            raise KeyError("Dispositivo não encontrado.")
        if not self.is_connected(device_id):
            raise RuntimeError("O PC está desconectado. Abra o OpenHUD Agent no computador.")
        if dev.emergency_stop and command in ("mt5_send_order",):
            raise PermissionError("STOP TRADING ativo: novas ordens estão bloqueadas.")
        perm = COMMAND_PERMISSION.get(command)
        if perm and not dev.permissions.get(perm, False):
            raise PermissionError(f"Permissão '{perm}' não concedida para este dispositivo.")
        if command == "mt5_send_order":
            # The mode decides which permission actually governs the order.
            required = "ALLOW_REAL_TRADING" if dev.trading_mode == "real" else "ALLOW_DEMO_TRADING"
            if dev.trading_mode not in ("demo", "real"):
                raise PermissionError(
                    "Ordens só podem ser enviadas nos modos DEMO ou REAL. "
                    f"Modo atual: {dev.trading_mode}."
                )
            if not dev.permissions.get(required, False):
                raise PermissionError(f"O modo {dev.trading_mode.upper()} exige a permissão {required}.")
        if self.loop is None:
            raise RuntimeError("Hub sem event loop ativo.")

        req_id = uuid.uuid4().hex
        # Register the waiter *before* sending so a fast agent reply cannot
        # arrive before the future exists.
        fut = asyncio.run_coroutine_threadsafe(self._await_response(req_id), self.loop)
        try:
            fut.result(timeout=2.0)  # ensure the future is registered
        except asyncio.TimeoutError:
            pass
        ok = self.send(device_id, {"type": "command", "id": req_id, "command": command, "args": args})
        if not ok:
            self._pending.pop(req_id, None)
            raise RuntimeError("Não foi possível enviar o comando ao PC.")
        try:
            return fut.result(timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"O PC não respondeu em {timeout:.0f}s.")

    async def _await_response(self, req_id: str) -> dict[str, Any]:
        fut: asyncio.Future = self.loop.create_future()  # type: ignore[union-attr]
        self._pending[req_id] = fut
        try:
            return await fut
        finally:
            self._pending.pop(req_id, None)

    def resolve_response(self, req_id: str, payload: dict[str, Any]) -> None:
        fut = self._pending.get(req_id)
        if fut and not fut.done():
            self.loop.call_soon_threadsafe(fut.set_result, payload)  # type: ignore[union-attr]

    def _notify(self, kind: str, device_id: str) -> None:
        cb = self.on_change
        if cb:
            try:
                cb(kind)
            except Exception:
                pass


# Global hub instance, wired to the runtime database in app.py.
hub: AgentHub | None = None


def init_hub(db) -> AgentHub:
    global hub
    hub = AgentHub(db)
    return hub


def get_hub() -> AgentHub:
    if hub is None:
        raise RuntimeError("Agent hub não inicializado.")
    return hub
