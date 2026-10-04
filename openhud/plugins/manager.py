"""Plugin manager.

Installs, enables, disables and removes plugins. Native plugins are built-in
and cannot be removed. Third-party plugins are described by a ``manifest.json``
dropped into ``data/plugins/<name>/``; installing only records the manifest
(no code is imported or executed here), and enabling a plugin whose risk is
HIGH/CRITICAL requires an explicit acknowledgement from the caller.

Plugins never see another user's data: plugin state is stored per instance and
the tool layer enforces the same workspace/permission boundaries as always.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .manifest import Manifest, parse_manifest
from .native import native_manifests, unavailable_plugins


class PluginManager:
    def __init__(self, db, plugins_dir: Path) -> None:
        self.db = db
        self.dir = Path(plugins_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._sync_native()

    # -- sync native -----------------------------------------------------
    def _sync_native(self) -> None:
        for m in native_manifests():
            row = self.db.query_one("SELECT id FROM plugins WHERE name=? AND builtin=1", (m.name,))
            if row:
                continue
            self._insert(m, builtin=True, enabled=True)

    def _insert(self, m: Manifest, builtin: bool, enabled: bool) -> None:
        pid = f"native:{m.name}" if builtin else f"ext:{m.name}"
        now = time.time()
        self.db.execute(
            "INSERT INTO plugins(id, name, version, author, description, source, risk, "
            "permissions, enabled, builtin, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, m.name, m.version, m.author, m.description, m.source, m.risk,
             json.dumps(m.permissions), 1 if enabled else 0, 1 if builtin else 0, now, now),
        )

    # -- queries ---------------------------------------------------------
    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM plugins ORDER BY builtin DESC, name")
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["permissions"] = json.loads(d["permissions"])
            except (json.JSONDecodeError, TypeError):
                d["permissions"] = []
            d["enabled"] = bool(d["enabled"])
            d["builtin"] = bool(d["builtin"])
            out.append(d)
        return out

    def store(self) -> dict[str, Any]:
        """Explore view: available, installed, active, disabled, updates."""
        installed = self.list()
        names = {p["name"] for p in installed}
        available = []
        for m in native_manifests():
            available.append({**m.to_dict(), "installed": m.name in names, "builtin": True})
        # Discover third-party manifests not yet installed.
        for m in self._discover():
            if m.name not in names:
                available.append({**m.to_dict(), "installed": False, "builtin": False})
        return {
            "available": available,
            "installed": [p for p in installed if p["source"] != "native"],
            "active": [p for p in installed if p["enabled"]],
            "disabled": [p for p in installed if not p["enabled"]],
            "updates": [],  # no remote registry configured -> honestly empty
            "unavailable": unavailable_plugins(),
            "registry_configured": False,
        }

    def _discover(self) -> list[Manifest]:
        out = []
        for child in sorted(self.dir.iterdir()):
            manifest_file = child / "manifest.json"
            if child.is_dir() and manifest_file.exists():
                try:
                    out.append(parse_manifest(json.loads(manifest_file.read_text())))
                except (ValueError, json.JSONDecodeError, OSError):
                    continue
        return out

    # -- mutations -------------------------------------------------------
    def install(self, name: str, *, acknowledge_risk: bool = False) -> dict[str, Any]:
        native = next((m for m in native_manifests() if m.name == name), None)
        if native:
            return {"ok": True, "message": f"Plugin nativo '{name}' já disponível.", "plugin": native.to_dict()}
        manifest = next((m for m in self._discover() if m.name == name), None)
        if manifest is None:
            return {"ok": False, "error": f"Plugin '{name}' não encontrado em {self.dir}."}
        if manifest.risk in ("HIGH", "CRITICAL") and not acknowledge_risk:
            return {"ok": False, "requires_ack": True, "risk": manifest.risk,
                    "error": f"O plugin '{name}' solicita permissões de risco {manifest.risk}. "
                             "Confirme explicitamente para instalar."}
        if self.db.query_one("SELECT id FROM plugins WHERE name=?", (name,)):
            return {"ok": False, "error": f"Plugin '{name}' já instalado."}
        self._insert(manifest, builtin=False, enabled=False)
        return {"ok": True, "plugin": manifest.to_dict()}

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM plugins WHERE name=?", (name,))
        if not row:
            return {"ok": False, "error": f"Plugin '{name}' não instalado."}
        self.db.execute("UPDATE plugins SET enabled=?, updated_at=? WHERE name=?",
                        (1 if enabled else 0, time.time(), name))
        return {"ok": True, "name": name, "enabled": enabled}

    def remove(self, name: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM plugins WHERE name=?", (name,))
        if not row:
            return {"ok": False, "error": f"Plugin '{name}' não instalado."}
        if row["builtin"]:
            return {"ok": False, "error": "Plugins nativos não podem ser removidos."}
        self.db.execute("DELETE FROM plugins WHERE name=?", (name,))
        return {"ok": True, "name": name}

    def active_tools(self) -> list[str]:
        """Tools exposed by enabled plugins (informational; the registry is the source of truth)."""
        active = [p for p in self.list() if p["enabled"]]
        by_name = {m.name: m for m in native_manifests()}
        tools: list[str] = []
        for p in active:
            m = by_name.get(p["name"])
            if m:
                tools.extend(m.tools)
        return sorted(set(tools))
