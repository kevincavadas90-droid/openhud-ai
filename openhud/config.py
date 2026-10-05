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
        # Optional external database. When set (e.g. a Neon/Supabase/Aiven
        # Postgres URL) the app uses it instead of SQLite, so data survives
        # container redeploys. OPENHUD_DATABASE_URL wins over the platform's
        # generic DATABASE_URL; empty means "use SQLite".
        self.database_url: str = (
            os.environ.get("OPENHUD_DATABASE_URL")
            or os.environ.get("DATABASE_URL", "")
        ).strip()
        self.key_path: Path = self.data_dir / "secret.key"
        self.workspace_dir: Path = Path(
            os.environ.get("OPENHUD_WORKSPACE", str(Path.cwd() / "workspace"))
        ).expanduser().resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.host: str = os.environ.get("OPENHUD_HOST", "0.0.0.0")
        # OPENHUD_PORT wins; otherwise honor the platform's PORT (Render,
        # Railway, Fly, Cloud Run) and fall back to 8000 locally.
        self.port: int = int(os.environ.get("OPENHUD_PORT") or os.environ.get("PORT") or "8000")
        # Opt-in CORS allow-list (comma-separated origins). Empty = disabled,
        # which is correct for the same-origin web UI. Never a wildcard default.
        self.cors_origins: list[str] = [
            o.strip() for o in os.environ.get("OPENHUD_CORS_ORIGINS", "").split(",") if o.strip()
        ]
        # Hard ceilings for safety; the user can lower them in settings.
        self.max_agent_steps: int = int(os.environ.get("OPENHUD_MAX_STEPS", "25"))
        self.shell_timeout: int = int(os.environ.get("OPENHUD_SHELL_TIMEOUT", "120"))

    @property
    def static_dir(self) -> Path:
        return Path(__file__).parent / "web" / "static"


settings = Settings()
