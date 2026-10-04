"""Code change sets with before/after/diff and accept/reject/revert.

Each change set is stored on disk under ``data/codex/<id>/``:

* ``meta.json``  — the operation list (path, before, after);
* ``before/``    — a snapshot of each touched file before the change.

Applying writes the ``after`` content; rejecting discards the set; reverting
restores the ``before`` snapshot. Nothing is destroyed silently: a file that
did not exist before is removed on revert, and an existing file is restored
from the snapshot.
"""
from __future__ import annotations

import difflib
import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def unified_diff(path: str, before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


@dataclass
class Change:
    path: str
    before: str | None       # None = file did not exist
    after: str | None        # None = delete the file
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "before": self.before,
            "after": self.after,
            "applied": self.applied,
            "diff": unified_diff(self.path, self.before or "", self.after or ""),
        }


@dataclass
class ChangeSet:
    id: str
    title: str
    root: Path
    changes: list[Change] = field(default_factory=list)
    status: str = "proposed"  # proposed | applied | rejected | reverted
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "status": self.status,
            "created_at": self.created_at,
            "changes": [c.to_dict() for c in self.changes],
        }


class ChangeStore:
    def __init__(self, base_dir: Path, workspace: Path) -> None:
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self.workspace = Path(workspace)

    def create(self, title: str, operations: list[dict[str, Any]]) -> ChangeSet:
        cs_id = uuid.uuid4().hex[:12]
        cs = ChangeSet(cs_id, title, self.workspace, created_at=time.time())
        for op in operations:
            rel = op["path"]
            target = self._resolve(rel)
            before = target.read_text(encoding="utf-8") if target.exists() and target.is_file() else None
            cs.changes.append(Change(rel, before, op.get("content")))
        self._persist(cs)
        return cs

    def apply(self, cs: ChangeSet) -> ChangeSet:
        for change in cs.changes:
            target = self._resolve(change.path)
            if change.after is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(change.after, encoding="utf-8")
            change.applied = True
        cs.status = "applied"
        self._persist(cs)
        return cs

    def revert(self, cs: ChangeSet) -> ChangeSet:
        for change in cs.changes:
            target = self._resolve(change.path)
            if change.before is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(change.before, encoding="utf-8")
            change.applied = False
        cs.status = "reverted"
        self._persist(cs)
        return cs

    def reject(self, cs: ChangeSet) -> ChangeSet:
        cs.status = "rejected"
        self._persist(cs)
        return cs

    def get(self, cs_id: str) -> ChangeSet | None:
        meta = self.base / cs_id / "meta.json"
        if not meta.exists():
            return None
        data = json.loads(meta.read_text())
        cs = ChangeSet(cs_id, data["title"], self.workspace, status=data["status"],
                       created_at=data["created_at"])
        cs.changes = [
            Change(c["path"], c["before"], c["after"], c.get("applied", False))
            for c in data["changes"]
        ]
        return cs

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        out = []
        for d in sorted(self.base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            cs = self.get(d.name)
            if cs:
                out.append(cs.to_dict())
        return out

    def _persist(self, cs: ChangeSet) -> None:
        d = self.base / cs.id
        (d / "before").mkdir(parents=True, exist_ok=True)
        for i, change in enumerate(cs.changes):
            if change.before is not None:
                snap = d / "before" / f"{i}.snapshot"
                snap.write_text(change.before, encoding="utf-8")
        (d / "meta.json").write_text(json.dumps(cs.to_dict(), ensure_ascii=False, indent=2))

    def _resolve(self, rel: str) -> Path:
        workspace = self.workspace.resolve()
        target = (workspace / rel).resolve()
        if target != workspace and workspace not in target.parents:
            raise ValueError(f"Caminho fora do workspace: {rel}")
        return target
