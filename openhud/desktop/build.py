"""Build the official OpenHUD Windows application with PyInstaller.

Run on Windows:

    pip install -r requirements-desktop.txt
    python -m openhud.desktop.build

Produces:
    dist/OpenHUD AI.exe              — the local app (server + tray)
    dist/openhud-agent.exe           — the PC agent (optional, same build)

The installer (installer/openhud.iss) then packages ``OpenHUD AI.exe`` into
``OpenHUD AI Setup.exe`` using Inno Setup.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _hidden_imports() -> list[str]:
    # Modules loaded dynamically (uvicorn workers, providers) or optional.
    mods = [
        "uvicorn", "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on", "websockets", "psutil", "pynvml",
        "openhud.web.app", "openhud.web.ai_api", "openhud.web.assistant_api",
        "openhud.web.agent_api", "openhud.web.trading_api", "openhud.desktop.app",
    ]
    for name in ("mss", "PIL", "pytesseract", "pyautogui", "pygetwindow", "pyperclip"):
        mods.append(name)
    return mods


def build_desktop() -> int:
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print("PyInstaller não instalado. Rode: pip install -r requirements-desktop.txt")
        return 1

    root = Path(__file__).resolve().parents[2]
    entry = Path(__file__).with_name("app.py")
    static = root / "openhud" / "web" / "static"
    sep = ";" if sys.platform == "win32" else ":"
    args = [
        str(entry),
        "--name", "OpenHUD AI",
        "--onefile",
        "--windowed",
        "--paths", str(root),
        "--add-data", f"{static}{sep}openhud/web/static",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "openhud",
        "--clean", "--noconfirm",
    ]
    for m in _hidden_imports():
        args += ["--hidden-import", m]
    print("PyInstaller", " ".join(args))
    pyi.run(args)
    print("Pronto: dist/OpenHUD AI" + (".exe" if sys.platform == "win32" else ""))
    return 0


def main() -> int:
    return build_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
