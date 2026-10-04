"""Production maintenance: schema version record, backup and restore.

The schema itself is created idempotently (``CREATE TABLE IF NOT EXISTS``) by
both backends, so migrations are additive and safe to re-run. This module
records the applied schema version and provides a *real* backup/restore path:

  * SQLite: copy the database with the WAL checkpointed, verify with
    ``PRAGMA integrity_check``, and store timestamped copies under
    ``data/backups/``. Restore replaces the live file after making a safety
    copy of the current one.
  * Postgres: backups are produced with ``pg_dump`` when the binary is present;
    otherwise the endpoint reports the honest reason and documents the command.
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def record_schema_version(db) -> None:
    """Store the schema version in settings (idempotent)."""
    try:
        if db.get_setting("schema_version") is None:
            db.set_setting("schema_version", SCHEMA_VERSION)
    except Exception:
        pass


def backup_dir(data_dir: Path) -> Path:
    d = data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_sqlite(db) -> bool:
    return db.__class__.__name__ == "Database"


def create_backup(db, data_dir: Path, label: str = "") -> dict[str, Any]:
    """Create a timestamped backup. Returns the real path or an honest error."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"openhud-{stamp}{('-' + label) if label else ''}"
    out_dir = backup_dir(data_dir)

    if _is_sqlite(db):
        src = Path(db.path)
        if not src.exists():
            return {"ok": False, "error": "Banco SQLite não encontrado."}
        dest = out_dir / f"{name}.db"
        try:
            # Use the SQLite backup API so WAL content is included consistently.
            with sqlite3.connect(src) as s, sqlite3.connect(dest) as d:
                s.backup(d)
            with sqlite3.connect(dest) as check:
                row = check.execute("PRAGMA integrity_check").fetchone()
            ok = bool(row and row[0] == "ok")
            return {"ok": ok, "path": str(dest), "bytes": dest.stat().st_size,
                    "integrity": row[0] if row else "unknown",
                    "error": "" if ok else "A verificação de integridade falhou."}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # Postgres: use pg_dump when available.
    url = getattr(db, "url", "")
    dump = shutil.which("pg_dump")
    if not url:
        return {"ok": False, "error": "Backup indisponível: banco sem URL."}
    if not dump:
        return {"ok": False,
                "error": "pg_dump não encontrado. Instale o cliente PostgreSQL ou use o backup do provedor.",
                "hint": "pg_dump \"$DATABASE_URL\" -f backup.sql"}
    import subprocess

    dest = out_dir / f"{name}.sql"
    try:
        proc = subprocess.run([dump, url, "-f", str(dest)], capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[-500:] or "pg_dump falhou."}
        return {"ok": True, "path": str(dest), "bytes": dest.stat().st_size}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def list_backups(data_dir: Path) -> list[dict[str, Any]]:
    d = backup_dir(data_dir)
    out = []
    for p in sorted(d.glob("openhud-*"), reverse=True):
        out.append({"name": p.name, "path": str(p), "bytes": p.stat().st_size,
                    "created_at": p.stat().st_mtime})
    return out


def restore_backup(db, data_dir: Path, name: str) -> dict[str, Any]:
    """Restore a SQLite backup, keeping a safety copy of the current DB."""
    if not _is_sqlite(db):
        return {"ok": False, "error": "Restauração automática só para SQLite; use psql para Postgres.",
                "hint": "psql \"$DATABASE_URL\" -f backup.sql"}
    src = backup_dir(data_dir) / Path(name).name
    if not src.exists():
        return {"ok": False, "error": "Backup não encontrado."}
    live = Path(db.path)
    try:
        safety = live.with_suffix(live.suffix + f".pre-restore-{int(time.time())}")
        if live.exists():
            shutil.copy2(live, safety)
        shutil.copy2(src, live)
        with sqlite3.connect(live) as check:
            row = check.execute("PRAGMA integrity_check").fetchone()
        ok = bool(row and row[0] == "ok")
        return {"ok": ok, "restored": str(src), "safety_copy": str(safety),
                "error": "" if ok else "Integridade do backup restaurado falhou."}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
