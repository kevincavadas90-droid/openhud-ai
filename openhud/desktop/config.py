"""Persistent configuration for the OpenHUD desktop application.

Stored as JSON under the user's config directory (``%APPDATA%\\OpenHUD`` on
Windows). It holds only what the app needs to reconnect: the server URL, the
device token issued by pairing, the chosen permissions and whether the
first-run wizard has already been completed. No passwords are stored here; the
device token is a scoped credential the server can revoke at any time.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "OpenHUD"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_PATH = config_dir() / "desktop.json"

# Permission groups shown to the user, mapping a friendly group to the
# underlying agent permission keys. This is presentation only; the server
# enforces the real keys.
PERMISSION_GROUPS: dict[str, dict[str, Any]] = {
    "basic": {
        "label": "Básico",
        "description": "Conexão e informações do sistema (CPU, RAM, disco, temperaturas).",
        "keys": ["system", "cpu", "ram", "storage", "temperatures"],
    },
    "screen": {
        "label": "Tela",
        "description": "Captura de tela e leitura de elementos (OCR).",
        "keys": ["screen"],
    },
    "control": {
        "label": "Controle",
        "description": "Mouse, teclado e foco de janelas. Permite que a IA aja no computador.",
        "keys": ["control"],
    },
    "automation": {
        "label": "Automação",
        "description": "Execução de tarefas e comandos autorizados.",
        "keys": ["commands", "processes", "games"],
    },
    "voice": {
        "label": "Voz",
        "description": "Microfone e áudio para conversar por voz.",
        "keys": ["voice"],
    },
}


@dataclass
class DesktopConfig:
    server: str = ""
    token: str = ""
    device_id: str = ""
    name: str = ""
    onboarded: bool = False
    autostart: bool = False
    groups: dict[str, bool] = field(default_factory=lambda: {
        "basic": True, "screen": False, "control": False,
        "automation": False, "voice": False,
    })
    extra: dict[str, Any] = field(default_factory=dict)

    # -- permissions -----------------------------------------------------
    def permissions(self) -> dict[str, bool]:
        """Expand the chosen groups into concrete agent permission keys."""
        perms: dict[str, bool] = {}
        for group, enabled in self.groups.items():
            spec = PERMISSION_GROUPS.get(group)
            if not spec:
                continue
            for key in spec["keys"]:
                perms[key] = bool(enabled)
        return perms

    def summary(self) -> str:
        on = [PERMISSION_GROUPS[g]["label"] for g, v in self.groups.items()
              if v and g in PERMISSION_GROUPS]
        return ", ".join(on) or "nenhuma"

    # -- persistence -----------------------------------------------------
    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "DesktopConfig":
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                cfg = cls(**known)
                return cfg
            except Exception:  # noqa: BLE001 - corrupt file should not crash the app
                pass
        return cls()

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def clear_credentials(self) -> None:
        self.token = ""
        self.device_id = ""
