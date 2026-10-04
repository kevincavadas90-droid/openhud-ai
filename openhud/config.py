"""Application configuration and paths.

All runtime state lives under OPENHUD_DATA_DIR (default: ./data).
No secrets are stored here; API keys live in the encrypted secret store.
"""
from __future__ import annotations

import os
from pathlib import Path


class Settings:
    """Process-wide settings resolved once at import time."""

    def __init__(self) -> None:
        self.data_dir: Path = Path(
            os.environ.get("OPENHUD_DATA_DIR", "data")
        ).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path: Path = self.data_dir / "openhud.db"
        self.key_path: Path = self.data_dir / "secret.key"
        self.workspace_dir: Path = Path(
            os.environ.get("OPENHUD_WORKSPACE", str(Path.cwd() / "workspace"))
        ).expanduser().resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.host: str = os.environ.get("OPENHUD_HOST", "0.0.0.0")
        self.port: int = int(os.environ.get("OPENHUD_PORT", "8000"))
        # Hard ceilings for safety; the user can lower them in settings.
        self.max_agent_steps: int = int(os.environ.get("OPENHUD_MAX_STEPS", "25"))
        self.shell_timeout: int = int(os.environ.get("OPENHUD_SHELL_TIMEOUT", "120"))

    @property
    def static_dir(self) -> Path:
        return Path(__file__).parent / "web" / "static"


settings = Settings()
