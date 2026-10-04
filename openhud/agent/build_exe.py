"""Build a standalone OpenHUD Agent executable with PyInstaller.

Run on the target platform (build the Windows .exe on Windows):

    pip install pyinstaller -r requirements-agent.txt
    python -m openhud.agent.build_exe

The result is a single file that runs the agent with no Python installed:
    dist/openhud-agent.exe --server https://host --pair 123456
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print("PyInstaller não instalado. Rode: pip install pyinstaller")
        return 1

    root = Path(__file__).resolve().parents[2]
    entry = Path(__file__).with_name("agent_client.py")
    name = "openhud-agent.exe" if sys.platform == "win32" else "openhud-agent"
    args = [
        str(entry),
        "--name", name,
        "--onefile",
        "--console",
        "--paths", str(root),
        "--hidden-import", "pynvml",
        "--clean",
        "--noconfirm",
    ]
    print("PyInstaller", " ".join(args))
    pyi.run(args)
    print(f"Pronto: dist/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
