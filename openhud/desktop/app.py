"""OpenHUD Desktop — the official Windows application.

A light launcher that starts the local OpenHUD server, opens the interface in
the browser and lives in the system tray. It is deliberately boring and safe:

  * it starts the same FastAPI app that ``python -m openhud`` runs;
  * it opens a single outbound connection only when you use the PC agent;
  * it does not install services, create hidden scheduled tasks, add startup
    entries or send telemetry — none of that code exists here;
  * the first run generates a local password and prints/shows it clearly.

On Windows it can also run in "agent mode" so the same executable can pair the
PC to a remote OpenHUD server.
"""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "OpenHUD AI"


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


CONFIG_DIR = _config_dir()
DATA_DIR = CONFIG_DIR / "data"
PASSWORD_FILE = CONFIG_DIR / "desktop-password.txt"


def ensure_password() -> str:
    """Return the local password, creating a strong one on first run."""
    env = os.environ.get("OPENHUD_PASSWORD")
    if env:
        return env
    if PASSWORD_FILE.exists():
        pw = PASSWORD_FILE.read_text(encoding="utf-8").strip()
        if pw:
            return pw
    pw = secrets.token_urlsafe(12)
    PASSWORD_FILE.write_text(pw, encoding="utf-8")
    try:  # best effort: restrict permissions on POSIX
        os.chmod(PASSWORD_FILE, 0o600)
    except Exception:
        pass
    return pw


def free_port(preferred: int = 8000) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def start_server(port: int) -> threading.Thread:
    """Start the OpenHUD web server in a background thread."""
    os.environ.setdefault("OPENHUD_HOST", "127.0.0.1")
    os.environ["OPENHUD_PORT"] = str(port)
    os.environ.setdefault("OPENHUD_DATA_DIR", str(DATA_DIR))
    os.environ.setdefault("OPENHUD_WORKSPACE", str(CONFIG_DIR / "workspace"))

    import uvicorn

    def _run() -> None:
        uvicorn.run("openhud.web.app:app", host="127.0.0.1", port=port, log_level="warning")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def _wait_ready(port: int, timeout: float = 30.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def run_tray(port: int, open_browser: bool) -> None:
    """System-tray launcher for the local app. Falls back to console."""
    try:
        import pystray  # type: ignore  # noqa: F401
        from PIL import Image, ImageDraw  # type: ignore  # noqa: F401
    except Exception as exc:
        print(f"[OpenHUD] bandeja indisponível ({exc}). Rodando no console. Ctrl+C para sair.")
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{port}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return
        return

    from .config import DesktopConfig
    from .runtime import AgentRuntime
    from .tray import TrayApp

    config = DesktopConfig.load()
    runtime = AgentRuntime(config)
    url = f"http://127.0.0.1:{port}"
    app = TrayApp(config, runtime, local_url=url,
                  on_diagnose=lambda: _print_diagnostics())
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run()


def _print_diagnostics() -> None:
    """Run the agent diagnostics and print the report (used by the tray)."""
    try:
        from openhud.agent.selfcheck import main as selfcheck_main

        selfcheck_main([])
    except Exception as exc:  # noqa: BLE001
        print(f"[OpenHUD] diagnóstico falhou: {type(exc).__name__}: {exc}")


def run_agent(server: str, pair: str | None, console: bool) -> int:
    """Run the desktop app as a PC agent connected to a remote server."""
    from .account import login_and_register
    from .config import DesktopConfig
    from .runtime import AgentRuntime

    config = DesktopConfig.load()
    if server:
        config.server = server.rstrip("/")
    if pair:
        config.extra["pair_code"] = pair

    if not config.onboarded and not console:
        from .wizard import ConsoleIO, run_wizard

        run_wizard(config, ConsoleIO(), pair_code=pair, login=login_and_register)

    if not config.server:
        print("[OpenHUD] Informe --agent <servidor> ou configure no assistente.")
        return 1
    if not config.token and not config.extra.get("pair_code"):
        print("[OpenHUD] Sem token nem código de pareamento. Rode com --pair <código>.")
        return 1

    runtime = AgentRuntime(config, on_state=lambda s, d: None)
    if console:
        runtime.start()
        print(f"[OpenHUD] {runtime.status_label()}. Ctrl+C para sair.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            runtime.stop()
        return 0

    from .tray import TrayApp

    app = TrayApp(config, runtime, local_url=None, on_diagnose=_print_diagnostics)
    app.run()
    return 0


def login_account(server: str, email: str, password: str) -> int:
    """Sign in with the account and register this computer.

    Keeps the account e-mail and the device token in the desktop config; the
    password is used once and never stored.
    """
    from .account import login_and_register
    from .config import DesktopConfig

    config = DesktopConfig.load()
    if server:
        config.server = server.rstrip("/")
    if not config.server:
        print("[OpenHUD] Informe --server <url> para entrar na conta.")
        return 1
    name = config.name or socket.gethostname() or "Meu PC"
    result = login_and_register(config.server, email, password, name, "windows")
    if not result.ok:
        print(f"[OpenHUD] Não foi possível entrar: {result.message}")
        return 2
    config.token = result.token
    config.device_id = result.device_id
    config.account_email = (result.user or {}).get("email", email)
    config.account_name = (result.user or {}).get("name", "")
    config.name = name
    config.save()
    print(f"[OpenHUD] Conectado como {config.account_email}. Computador registrado na conta.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} — aplicativo local")
    parser.add_argument("--port", type=int, default=0, help="Porta (0 = automática)")
    parser.add_argument("--no-browser", action="store_true", help="Não abrir o navegador")
    parser.add_argument("--console", action="store_true", help="Rodar no console (sem bandeja)")
    parser.add_argument("--agent", metavar="SERVER", help="Rodar como agente conectado a um servidor")
    parser.add_argument("--pair", help="Código de pareamento (com --agent)")
    parser.add_argument("--login", action="store_true", help="Entrar com a conta (e-mail/senha) e registrar este PC")
    parser.add_argument("--server", help="URL do servidor OpenHUD (para --login/--agent)")
    parser.add_argument("--email", help="E-mail da conta (com --login)")
    parser.add_argument("--password", help="Senha da conta (com --login; não é armazenada)")
    parser.add_argument("--onboard", action="store_true", help="Rodar só o assistente de primeira execução")
    parser.add_argument("--diagnose", action="store_true", help="Rodar o diagnóstico do agente e sair")
    parser.add_argument("--permissions", action="store_true", help="Mostrar as permissões atuais e sair")
    args = parser.parse_args(argv)

    if args.diagnose:
        _print_diagnostics()
        return 0

    if args.permissions:
        from .config import PERMISSION_GROUPS, DesktopConfig

        config = DesktopConfig.load()
        print(f"Servidor: {config.server or '(não configurado)'}")
        print(f"Pareado: {'sim' if config.token else 'não'}")
        for group, spec in PERMISSION_GROUPS.items():
            mark = "ON " if config.groups.get(group) else "off"
            print(f"  [{mark}] {spec['label']}: {spec['description']}")
        return 0

    if args.onboard:
        from .config import DesktopConfig
        from .wizard import ConsoleIO, run_wizard

        run_wizard(DesktopConfig.load(), ConsoleIO(), pair_code=args.pair)
        return 0

    if args.login:
        email = args.email or input("E-mail: ").strip()
        password = args.password or input("Senha: ").strip()
        return login_account(args.server or args.agent or "", email, password)

    if args.agent:
        return run_agent(args.agent, args.pair, args.console)

    pw = ensure_password()
    port = args.port or free_port(8000)
    print(f"[OpenHUD] Iniciando em http://127.0.0.1:{port}")
    print(f"[OpenHUD] Senha local: {pw}")
    start_server(port)
    if not _wait_ready(port):
        print("[OpenHUD] O servidor não ficou pronto a tempo. Verifique os logs.")
        return 1
    print("[OpenHUD] Pronto. Abra o endereço acima e faça login com a senha mostrada.")

    if args.console:
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{port}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
    run_tray(port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
