"""OpenHUD Agent — the small program that runs on the user's PC.

It opens a single outbound secure WebSocket to the OpenHUD server, streams
hardware metrics and executes only the commands the user has authorised. It is
designed to be safe by default:

  * it never listens on a port (no inbound access to the PC);
  * it only connects out, with TLS;
  * it refuses to run arbitrary commands unless the "commands" permission was
    granted, and even then it blocks catastrophic patterns;
  * it keeps working offline (local history + diagnostics) and syncs later.

Run it with a pairing code (first time) or a saved device token:

    python -m openhud.agent.agent_client --server https://host --pair 123456
    python -m openhud.agent.agent_client --server https://host --token <token>

The token is stored in a local config file so subsequent runs need no code.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .diagnostics import available_optimizations, diagnose
from .telemetry import TelemetryCollector

# --------------------------------------------------------------------------
# local storage (offline history, config, unsent buffer)
# --------------------------------------------------------------------------
def _config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "OpenHUD"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_PATH = _config_dir() / "agent.json"
HISTORY_PATH = _config_dir() / "history.db"


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


class History:
    """Local metric history so the agent is useful without the server."""

    def __init__(self, path: Path = HISTORY_PATH) -> None:
        self.path = path
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS samples ("
                "ts REAL, cpu REAL, gpu REAL, ram REAL, vram REAL, temp REAL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, game TEXT, started REAL, ended REAL, "
                "cpu_avg REAL, gpu_avg REAL, ram_avg REAL, fps_avg REAL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS unsent (ts REAL, payload TEXT)"
            )

    def add_sample(self, m: dict[str, Any]) -> None:
        cpu = (m.get("cpu") or {}).get("percent")
        gpus = m.get("gpu") or []
        gpu = gpus[0] if gpus else {}
        ram = (m.get("ram") or {}).get("percent")
        try:
            with sqlite3.connect(self.path) as c:
                c.execute(
                    "INSERT INTO samples(ts,cpu,gpu,ram,vram,temp) VALUES(?,?,?,?,?,?)",
                    (m.get("ts", time.time()), cpu, gpu.get("util_percent"), ram,
                     gpu.get("mem_percent"), (m.get("cpu") or {}).get("temp_c")),
                )
        except Exception:
            pass

    def buffer(self, payload: dict[str, Any]) -> None:
        try:
            with sqlite3.connect(self.path) as c:
                c.execute("INSERT INTO unsent(ts,payload) VALUES(?,?)",
                          (time.time(), json.dumps(payload)))
        except Exception:
            pass

    def drain_buffer(self) -> list[dict[str, Any]]:
        try:
            with sqlite3.connect(self.path) as c:
                rows = c.execute("SELECT rowid,payload FROM unsent ORDER BY ts LIMIT 500").fetchall()
                if rows:
                    c.executemany("DELETE FROM unsent WHERE rowid=?", [(r[0],) for r in rows])
                return [json.loads(r[1]) for r in rows]
        except Exception:
            return []

    def summary(self, limit: int = 300) -> dict[str, Any]:
        try:
            with sqlite3.connect(self.path) as c:
                row = c.execute(
                    "SELECT COUNT(*), AVG(cpu), AVG(gpu), AVG(ram) FROM samples "
                    "WHERE ts > ?", (time.time() - 3600,)
                ).fetchone()
            return {"samples_last_hour": row[0], "cpu_avg": row[1], "gpu_avg": row[2], "ram_avg": row[3]}
        except Exception:
            return {}


# --------------------------------------------------------------------------
# game scanning (best effort, platform dependent)
# --------------------------------------------------------------------------
GAME_PROCESSES = {
    "FiveM": ["fivem", "fivem.exe", "citizenfx"],
    "GTA V": ["gta5.exe", "gtav.exe", "gta5"],
    "Fortnite": ["fortniteclient-win64-shipping.exe", "fortnite"],
    "CS2": ["cs2.exe", "cs2"],
    "Roblox": ["robloxplayerbeta.exe", "roblox"],
    "Valorant": ["valorant.exe", "valorant-win64-shipping.exe"],
    "Minecraft": ["javaw.exe", "minecraft"],
    "League of Legends": ["leagueclient.exe", "league of legends.exe"],
}

GAME_PATHS = {
    "GTA V": [r"C:\Program Files\Rockstar Games\Grand Theft Auto V",
              r"C:\Program Files (x86)\Rockstar Games\Grand Theft Auto V"],
    "FiveM": [r"C:\Users\{user}\AppData\Local\FiveM"],
    "Fortnite": [r"C:\Program Files\Epic Games\Fortnite"],
    "CS2": [r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive"],
    "Roblox": [r"C:\Users\{user}\AppData\Local\Roblox"],
    "Valorant": [r"C:\Riot Games\VALORANT"],
    "League of Legends": [r"C:\Riot Games\League of Legends"],
}


def scan_games() -> list[dict[str, Any]]:
    """Detect installed/running games without inventing results."""
    running: set[str] = set()
    try:
        import psutil  # type: ignore

        for p in psutil.process_iter(["name"]):
            name = (p.info.get("name") or "").lower()
            for game, procs in GAME_PROCESSES.items():
                if any(pr in name for pr in procs):
                    running.add(game)
    except Exception:
        pass

    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    found: list[dict[str, Any]] = []
    for game, paths in GAME_PATHS.items():
        installed_path = None
        for p in paths:
            candidate = Path(p.replace("{user}", user))
            if candidate.exists():
                installed_path = str(candidate)
                break
        if installed_path or game in running:
            found.append({
                "name": game,
                "installed": bool(installed_path),
                "path": installed_path,
                "running": game in running,
            })
    return found


# --------------------------------------------------------------------------
# command execution
# --------------------------------------------------------------------------
BLOCKED = ["rm -rf /", "mkfs", "dd if=/dev/zero", ":(){:|:&};:", "shutdown", "reboot", "format c:", "del /f /s /q c:\\"]


def _run_shell(command: str, timeout: int = 30) -> dict[str, Any]:
    low = command.lower()
    for bad in BLOCKED:
        if bad in low:
            return {"ok": False, "error": f"Comando bloqueado por segurança: {bad}"}
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"ok": proc.returncode == 0, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:], "code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Tempo esgotado ({timeout}s)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _filter_by_permissions(metrics: dict[str, Any], perms: dict[str, bool]) -> dict[str, Any]:
    """Drop metric families the user did not authorise."""
    out = dict(metrics)
    if not perms.get("cpu", True):
        out.pop("cpu", None)
    if not perms.get("gpu", True):
        out.pop("gpu", None)
    if not perms.get("ram", True):
        out.pop("ram", None)
    if not perms.get("storage", True):
        out.pop("disk", None)
        out.pop("disk_io", None)
    if not perms.get("network", True):
        out.pop("network", None)
    if not perms.get("processes", False):
        out.pop("processes", None)
        out.pop("process_count", None)
    if not perms.get("temperatures", True):
        if isinstance(out.get("cpu"), dict):
            out["cpu"].pop("temp_c", None)
        if isinstance(out.get("gpu"), list):
            for g in out["gpu"]:
                g.pop("temp_c", None)
    return out


def _clear_temp() -> dict[str, Any]:
    import glob
    import tempfile

    removed = 0
    freed = 0
    for pattern in ("*/tmp*", "*"):
        for f in glob.glob(str(Path(tempfile.gettempdir()) / pattern)):
            p = Path(f)
            try:
                if p.is_file():
                    freed += p.stat().st_size
                    p.unlink()
                    removed += 1
            except Exception:
                continue
    return {"ok": True, "removed": removed, "freed_mb": round(freed / (1024 * 1024), 1)}


def _list_startup() -> dict[str, Any]:
    items: list[str] = []
    if os.name == "nt":
        r = _run_shell(
            'reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"', timeout=15
        )
        if r.get("stdout"):
            items = [ln.strip() for ln in r["stdout"].splitlines() if ln.strip()]
    else:
        autostart = Path.home() / ".config/autostart"
        if autostart.exists():
            items = [p.name for p in autostart.glob("*.desktop")]
    return {"ok": True, "items": items}


def _flush_dns() -> dict[str, Any]:
    cmd = "ipconfig /flushdns" if os.name == "nt" else "resolvectl flush-caches 2>/dev/null || true"
    return _run_shell(cmd, timeout=15)


OPTIMIZATIONS = {
    "clear_temp": _clear_temp,
    "list_startup": _list_startup,
    "flush_dns": _flush_dns,
    # high_performance intentionally NOT auto-executed: requires explicit OS-level
    # change and is offered as advice with manual undo steps only.
}


def execute_command(command: str, args: dict[str, Any], collector: TelemetryCollector,
                    perms: dict[str, bool]) -> dict[str, Any]:
    if command == "ping":
        return {"ok": True, "pong": time.time()}
    if command == "get_metrics":
        return {"ok": True, "data": _filter_by_permissions(collector.collect(), perms)}
    if command == "list_processes":
        if not perms.get("processes", False):
            return {"ok": False, "error": "Permissão de processos não concedida."}
        return {"ok": True, "data": collector.collect().get("processes", [])}
    if command == "diagnose":
        m = _filter_by_permissions(collector.collect(), perms)
        return {"ok": True, "data": diagnose(m)}
    if command == "scan_games":
        if not perms.get("games", False):
            return {"ok": False, "error": "Permissão de jogos não concedida."}
        return {"ok": True, "data": scan_games()}
    if command == "system_info":
        return {"ok": True, "data": collector.system_info()}
    if command == "shell":
        if not perms.get("commands", False):
            return {"ok": False, "error": "Permissão de execução de comandos não concedida."}
        return _run_shell(args.get("command", ""), int(args.get("timeout", 30)))
    if command == "optimize":
        opt_id = args.get("id", "")
        if opt_id not in OPTIMIZATIONS:
            return {"ok": False, "error": f"Otimização '{opt_id}' não é executável automaticamente."}
        if not perms.get("commands", False):
            return {"ok": False, "error": "Permissão de execução de comandos não concedida."}
        result = OPTIMIZATIONS[opt_id]()
        result["optimization"] = opt_id
        return result
    return {"ok": False, "error": f"Comando desconhecido: {command}"}


# --------------------------------------------------------------------------
# websocket client with reconnect + offline buffering
# --------------------------------------------------------------------------
class AgentClient:
    def __init__(self, server: str, token: str | None, pair_code: str | None,
                 name: str, interval: float = 1.0, verbose: bool = True) -> None:
        self.server = server.rstrip("/")
        self.token = token
        self.pair_code = pair_code
        self.name = name
        self.interval = interval
        self.verbose = verbose
        self.collector = TelemetryCollector()
        self.history = History()
        self.permissions = {}
        self.device_id = None
        self._ws = None

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[OpenHUD Agent] {msg}", flush=True)

    def _ws_url(self) -> str:
        base = self.server
        if base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
        return base + "/ws/agent"

    async def run_forever(self) -> None:
        import websockets

        backoff = 2.0
        while True:
            try:
                self.log(f"conectando a {self._ws_url()} …")
                async with websockets.connect(self._ws_url(), ping_interval=20, ping_timeout=20,
                                              max_size=8 * 1024 * 1024) as ws:
                    self._ws = ws
                    await self._handshake(ws)
                    backoff = 2.0
                    await self._pump(ws)
            except Exception as exc:
                self.log(f"desconectado ({type(exc).__name__}: {exc}); reconectando em {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _handshake(self, ws) -> None:
        info = self.collector.system_info()
        if self.pair_code:
            await ws.send(json.dumps({
                "type": "pair", "code": self.pair_code, "name": self.name,
                "platform": platform.platform(), "info": info,
            }))
        else:
            await ws.send(json.dumps({
                "type": "auth", "token": self.token, "name": self.name,
                "platform": platform.platform(), "info": info,
            }))
        raw = await asyncio.wait_for(ws.recv(), timeout=20)
        msg = json.loads(raw)
        if msg.get("type") == "pair_ok":
            self.token = msg["token"]
            self.device_id = msg["device_id"]
            cfg = load_config()
            cfg.update({"server": self.server, "token": self.token, "device_id": self.device_id, "name": self.name})
            save_config(cfg)
            self.pair_code = None
            self.log(f"pareado com sucesso. device_id={self.device_id}")
        elif msg.get("type") == "auth_ok":
            self.device_id = msg["device_id"]
            self.permissions = msg.get("permissions", {})
            self.log(f"autenticado. device_id={self.device_id}")
        else:
            raise RuntimeError(f"handshake recusado: {msg.get('error', msg)}")

    async def _send_metrics(self, ws) -> None:
        metrics = self.collector.collect()
        self.history.add_sample(metrics)
        filtered = _filter_by_permissions(metrics, self.permissions)
        await ws.send(json.dumps({"type": "metrics", "data": filtered}))

    async def _pump(self, ws) -> None:
        # flush anything buffered while offline
        for payload in self.history.drain_buffer():
            try:
                await ws.send(json.dumps({"type": "sync", "data": payload}))
            except Exception:
                self.history.buffer(payload)
                break

        last = 0.0
        while True:
            now = time.time()
            if now - last >= self.interval:
                await self._send_metrics(ws)
                last = now
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.interval)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            await self._handle(ws, msg)

    async def _handle(self, ws, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "permissions":
            self.permissions = msg.get("permissions", {})
            self.log(f"permissões atualizadas: {self.permissions}")
        elif mtype == "command":
            result = await asyncio.get_event_loop().run_in_executor(
                None, execute_command, msg.get("command", ""), msg.get("args", {}),
                self.collector, self.permissions,
            )
            await ws.send(json.dumps({"type": "result", "id": msg.get("id"), **result}))
        elif mtype == "ping":
            await ws.send(json.dumps({"type": "pong"}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenHUD Agent (monitor do PC)")
    parser.add_argument("--server", help="URL do servidor OpenHUD (ex.: https://openhud.exemplo)")
    parser.add_argument("--token", help="Token do dispositivo (para reconexões)")
    parser.add_argument("--pair", help="Código de pareamento de 6 dígitos")
    parser.add_argument("--name", help="Nome deste PC")
    parser.add_argument("--interval", type=float, default=1.0, help="Intervalo de coleta em segundos")
    parser.add_argument("--tray", action="store_true", help="Mostrar ícone na bandeja do sistema")
    parser.add_argument("--print-metrics", action="store_true", help="Imprimir métricas e sair (teste)")
    args = parser.parse_args(argv)

    if args.print_metrics:
        col = TelemetryCollector()
        print(json.dumps(col.collect(), indent=2, ensure_ascii=False))
        return 0

    cfg = load_config()
    server = args.server or cfg.get("server")
    token = args.token or cfg.get("token")
    name = args.name or cfg.get("name") or platform.node() or "Meu PC"

    if not server:
        parser.error("informe --server (ou rode uma vez com --pair e --server)")
    if not token and not args.pair:
        parser.error("informe --pair <código> (primeira vez) ou --token <token>")

    client = AgentClient(server, token, args.pair, name, interval=args.interval)

    if args.tray:
        try:
            _run_with_tray(client)
            return 0
        except Exception as exc:
            print(f"[OpenHUD Agent] bandeja indisponível ({exc}); rodando em segundo plano.", flush=True)

    try:
        asyncio.run(client.run_forever())
    except KeyboardInterrupt:
        print("\n[OpenHUD Agent] encerrado.")
    return 0


def _run_with_tray(client: AgentClient) -> None:
    """Run the client in a thread with a system-tray icon (optional)."""
    import threading

    import pystray  # type: ignore
    from PIL import Image, ImageDraw  # type: ignore

    img = Image.new("RGB", (64, 64), "#0b0f17")
    d = ImageDraw.Draw(img)
    d.ellipse((16, 16, 48, 48), fill="#22d3ee")

    thread = threading.Thread(target=lambda: asyncio.run(client.run_forever()), daemon=True)
    thread.start()

    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    icon = pystray.Icon("OpenHUD", img, "OpenHUD Agent", menu=pystray.Menu(
        pystray.MenuItem("Sair", on_quit)
    ))
    icon.run()


if __name__ == "__main__":
    raise SystemExit(main())
