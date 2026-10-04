"""Agent API: the site-side endpoints that pair and control PC agents.

Two surfaces:
  * ``/ws/agent`` — the WebSocket an OpenHUD Agent connects to. It authenticates
    with a device token (or redeems a pairing code) and then streams metrics.
  * ``/api/agents/*`` — REST endpoints for the authenticated web session to list
    devices, grant permissions, run diagnostics/optimisations and send commands.

A "local" pseudo-device exposes the server host's own metrics so the dashboard
is useful immediately, before any PC is connected. It is clearly labelled.
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..agent.diagnostics import available_optimizations, diagnose, suggest_game_profile
from ..agent.telemetry import TelemetryCollector
from ..core.agent_hub import PERMISSION_KEYS, get_hub
from ..core.runtime import runtime

router = APIRouter()

# Rolling in-memory history per device (last ~300 samples) for the charts.
_history: dict[str, deque] = {}
_HISTORY_LEN = 300
# Server-host telemetry collector for the "local" pseudo-device.
_local_collector = TelemetryCollector()
_LOCAL_ID = "local"


class PermissionsPayload(BaseModel):
    permissions: dict[str, bool]


class CommandPayload(BaseModel):
    command: str
    args: dict[str, Any] = {}


class OptimizePayload(BaseModel):
    id: str


class GameProfilePayload(BaseModel):
    game: str
    fps: float | None = None


def _record(device_id: str, metrics: dict[str, Any]) -> None:
    dq = _history.setdefault(device_id, deque(maxlen=_HISTORY_LEN))
    gpus = metrics.get("gpu") or []
    gpu = gpus[0] if gpus else {}
    dq.append({
        "ts": metrics.get("ts"),
        "cpu": (metrics.get("cpu") or {}).get("percent"),
        "gpu": gpu.get("util_percent"),
        "ram": (metrics.get("ram") or {}).get("percent"),
        "vram": gpu.get("mem_percent"),
    })


# --------------------------------------------------------------------------
# WebSocket endpoint used by the agent
# --------------------------------------------------------------------------
@router.websocket("/ws/agent")
async def agent_ws(ws: WebSocket) -> None:
    await ws.accept()
    hub = get_hub()
    hub.loop = asyncio.get_running_loop()
    device = None
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=25)
        hello = json.loads(raw)
        if hello.get("type") == "pair":
            try:
                result = hub.redeem_pairing_code(
                    hello.get("code", ""), hello.get("name", "Meu PC"),
                    hello.get("platform", "unknown"), hello.get("info", {}),
                )
            except ValueError as exc:
                await ws.send_text(json.dumps({"type": "pair_error", "error": str(exc)}))
                await ws.close()
                return
            device = hub.get_device(result["device_id"])
            await ws.send_text(json.dumps({
                "type": "pair_ok", "device_id": result["device_id"],
                "token": result["token"], "permissions": device.permissions,
            }))
        elif hello.get("type") == "auth":
            device = hub.verify_token(hello.get("token", ""))
            if device is None:
                await ws.send_text(json.dumps({"type": "auth_error", "error": "Token inválido ou revogado."}))
                await ws.close()
                return
            if hello.get("info"):
                device.info = hello["info"]
            await ws.send_text(json.dumps({
                "type": "auth_ok", "device_id": device.id,
                "permissions": device.permissions,
            }))
        else:
            await ws.send_text(json.dumps({"type": "error", "error": "Primeira mensagem deve ser 'pair' ou 'auth'."}))
            await ws.close()
            return

        hub.attach(device, ws)
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "metrics":
                data = msg.get("data") or {}
                hub.touch(device.id, data)
                _record(device.id, data)
            elif mtype == "result":
                hub.resolve_response(msg.get("id", ""), msg)
            elif mtype == "mt5_status":
                hub.record_mt5_status(device.id, msg.get("data") or {})
            elif mtype == "sync":
                _record(device.id, msg.get("data") or {})
            elif mtype == "pong":
                hub.touch(device.id)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        if device is not None:
            hub.detach(device.id)


# --------------------------------------------------------------------------
# REST endpoints used by the browser
# --------------------------------------------------------------------------
@router.post("/api/agents/pairing")
def create_pairing() -> dict[str, Any]:
    return get_hub().create_pairing_code()


@router.get("/api/agents")
def list_agents() -> dict[str, Any]:
    hub = get_hub()
    return {
        "devices": hub.list_devices(),
        "permission_keys": PERMISSION_KEYS,
        "local_id": _LOCAL_ID,
    }


@router.post("/api/agents/local")
def ensure_local() -> dict[str, Any]:
    """Register/refresh the server-host pseudo-device so the dashboard works."""
    hub = get_hub()
    metrics = _local_collector.collect()
    _record(_LOCAL_ID, metrics)
    dev = hub.get_device(_LOCAL_ID)
    if dev is None:
        # Register directly (no pairing needed: this is the server's own host).
        from ..core.agent_hub import Device, _hash_token
        import uuid as _uuid
        import time as _time

        dev = Device(
            id=_LOCAL_ID, name="Servidor OpenHUD (este host)",
            platform=_local_collector.system_info().get("platform", "server"),
            token_hash=_hash_token(_uuid.uuid4().hex), created_at=_time.time(),
            last_seen=_time.time(), info=_local_collector.system_info(),
        )
        hub._devices[_LOCAL_ID] = dev
    dev.metrics = metrics
    dev.metrics_at = metrics.get("ts", 0.0)
    dev.last_seen = metrics.get("ts", 0.0)
    dev.info = _local_collector.system_info()
    return dev.public()


@router.get("/api/agents/{device_id}")
def get_agent(device_id: str) -> dict[str, Any]:
    hub = get_hub()
    dev = hub.get_device(device_id)
    if dev is None:
        raise HTTPException(404, "Dispositivo não encontrado")
    # The server-host pseudo-device has no agent process pushing data, so we
    # sample it here to keep the dashboard live.
    if device_id == _LOCAL_ID:
        metrics = _local_collector.collect()
        _record(_LOCAL_ID, metrics)
        dev.metrics = metrics
        dev.metrics_at = metrics.get("ts", 0.0)
        dev.last_seen = metrics.get("ts", 0.0)
        dev.info = _local_collector.system_info()
    return dev.public()


@router.get("/api/agents/{device_id}/history")
def agent_history(device_id: str) -> dict[str, Any]:
    if get_hub().get_device(device_id) is None:
        raise HTTPException(404, "Dispositivo não encontrado")
    return {"samples": list(_history.get(device_id, []))}


@router.post("/api/agents/{device_id}/permissions")
def set_permissions(device_id: str, payload: PermissionsPayload) -> dict[str, Any]:
    try:
        return get_hub().set_permissions(device_id, payload.permissions)
    except KeyError:
        raise HTTPException(404, "Dispositivo não encontrado")


@router.post("/api/agents/{device_id}/revoke")
def revoke(device_id: str) -> dict[str, bool]:
    return {"revoked": get_hub().revoke(device_id)}


@router.post("/api/agents/{device_id}/command")
def send_command(device_id: str, payload: CommandPayload) -> dict[str, Any]:
    hub = get_hub()
    try:
        return hub.request(device_id, payload.command, payload.args, timeout=20.0)
    except KeyError:
        raise HTTPException(404, "Dispositivo não encontrado")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(504, str(exc))


@router.post("/api/agents/{device_id}/diagnose")
def run_diagnose(device_id: str) -> dict[str, Any]:
    hub = get_hub()
    dev = hub.get_device(device_id)
    if dev is None:
        raise HTTPException(404, "Dispositivo não encontrado")
    # Prefer live data straight from the device; fall back to the last snapshot.
    metrics = dev.metrics
    if device_id != _LOCAL_ID and hub.is_connected(device_id):
        try:
            result = hub.request(device_id, "get_metrics", {}, timeout=10.0)
            if result.get("ok"):
                metrics = result.get("data") or metrics
        except Exception:
            pass
    elif device_id == _LOCAL_ID:
        metrics = _local_collector.collect()
        _record(_LOCAL_ID, metrics)
    return diagnose(metrics)


@router.get("/api/agents/{device_id}/optimizations")
def list_optimizations(device_id: str) -> list[dict[str, Any]]:
    return available_optimizations()


@router.post("/api/agents/{device_id}/optimize")
def run_optimize(device_id: str, payload: OptimizePayload) -> dict[str, Any]:
    hub = get_hub()
    try:
        return hub.request(device_id, "optimize", {"id": payload.id}, timeout=60.0)
    except KeyError:
        raise HTTPException(404, "Dispositivo não encontrado")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(504, str(exc))


@router.get("/api/agents/{device_id}/games")
def scan_games(device_id: str) -> dict[str, Any]:
    hub = get_hub()
    try:
        return hub.request(device_id, "scan_games", {}, timeout=30.0)
    except KeyError:
        raise HTTPException(404, "Dispositivo não encontrado")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (TimeoutError, RuntimeError) as exc:
        # No agent to scan with: report honestly instead of inventing games.
        return {"ok": False, "error": str(exc), "data": []}


@router.post("/api/agents/{device_id}/game-profile")
def game_profile(device_id: str, payload: GameProfilePayload) -> dict[str, Any]:
    hub = get_hub()
    dev = hub.get_device(device_id)
    if dev is None:
        raise HTTPException(404, "Dispositivo não encontrado")
    metrics = dev.metrics
    if device_id == _LOCAL_ID:
        metrics = _local_collector.collect()
    profile = suggest_game_profile(payload.game, metrics)
    if payload.fps is not None:
        profile["measured_fps"] = payload.fps
    return profile
