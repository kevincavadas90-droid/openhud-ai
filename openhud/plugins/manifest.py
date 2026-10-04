"""Plugin manifest and permission model.

A manifest declares the plugin's identity, the permissions it requests, its
dependencies and the tools it exposes. Permissions are classified in tiers so
the install UI can show the real risk before anything runs.

Manifests are untrusted input: parsing never imports or executes plugin code,
and the declared permissions are only *requests* — the host still enforces
its own gates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Permission tiers, ordered by risk.
TIERS = ["SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

PERMISSION_TIERS: dict[str, str] = {
    "read_telemetry": "SAFE",
    "read_time": "SAFE",
    "read_files": "LOW",
    "write_files": "MEDIUM",
    "read_config": "LOW",
    "write_config": "MEDIUM",
    "network": "MEDIUM",
    "execute_command": "HIGH",
    "control_processes": "HIGH",
    "system_settings": "CRITICAL",
    "credentials": "CRITICAL",
}

# A plugin's overall risk is the highest tier among its requested permissions.
def risk_of(permissions: list[str]) -> str:
    highest = 0
    for perm in permissions:
        tier = PERMISSION_TIERS.get(perm, "HIGH")  # unknown permission = treat as risky
        highest = max(highest, TIERS.index(tier))
    return TIERS[highest]


@dataclass
class Manifest:
    name: str
    version: str = "0.0.0"
    author: str = ""
    description: str = ""
    source: str = "native"
    permissions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    entry: str = ""

    @property
    def risk(self) -> str:
        return risk_of(self.permissions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version, "author": self.author,
            "description": self.description, "source": self.source,
            "permissions": self.permissions,
            "permission_tiers": {p: PERMISSION_TIERS.get(p, "HIGH") for p in self.permissions},
            "dependencies": self.dependencies, "tools": self.tools,
            "risk": self.risk, "entry": self.entry,
        }


def parse_manifest(data: dict[str, Any]) -> Manifest:
    """Parse a manifest dict, tolerating missing fields but requiring a name."""
    if not isinstance(data, dict) or not data.get("name"):
        raise ValueError("Manifesto inválido: campo 'name' é obrigatório.")
    perms = data.get("permissions") or []
    if not isinstance(perms, list):
        raise ValueError("Manifesto inválido: 'permissions' deve ser uma lista.")
    return Manifest(
        name=str(data["name"])[:100],
        version=str(data.get("version", "0.0.0"))[:40],
        author=str(data.get("author", ""))[:100],
        description=str(data.get("description", ""))[:500],
        source=str(data.get("source", "native"))[:60],
        permissions=[str(p) for p in perms][:50],
        dependencies=[str(d) for d in (data.get("dependencies") or [])][:50],
        tools=[str(t) for t in (data.get("tools") or [])][:50],
        entry=str(data.get("entry", ""))[:200],
    )
