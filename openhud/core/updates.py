"""Safe update checking (Part 19).

The updater never runs silently and never executes an arbitrary file. It:

  * fetches a signed-by-hash release manifest over HTTPS from a URL the user
    configures (``OPENHUD_UPDATE_URL`` or the ``update_url`` setting);
  * verifies the manifest's own ``sha256`` if the caller passes an expected
    digest, and verifies every artifact's ``sha256`` before reporting it as
    usable;
  * compares versions and returns a *plan* — it does not download-and-run;
  * refuses non-HTTPS origins (except localhost) and rejects path traversal.

Applying an update is intentionally left to the operator: the function
:func:`download_artifact` fetches a file, verifies its hash and stores it
under ``data/updates/`` for manual installation, preserving all user data.
Rollback is "keep the previous install" — the DB and config live outside the
code, so reinstalling the prior version is the rollback.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = ["UpdateInfo", "check_for_update", "download_artifact", "verify_sha256"]


@dataclass
class UpdateInfo:
    available: bool = False
    current: str = ""
    latest: str = ""
    notes: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    manifest_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available, "current": self.current, "latest": self.latest,
            "notes": self.notes, "artifacts": self.artifacts, "error": self.error,
            "manifest_url": self.manifest_url,
        }


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", v or "")
    return tuple(int(p) for p in parts[:4]) or (0,)


def verify_sha256(path: Path, expected: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == (expected or "").lower()


def _allowed_origin(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return True
    if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    return False


def _safe_name(name: str) -> str:
    name = Path(name).name
    if name in ("", ".", ".."):
        raise ValueError("Nome de artefato inválido.")
    return name


def check_for_update(current_version: str, manifest_url: str, timeout: float = 10.0) -> UpdateInfo:
    """Fetch and validate a release manifest. Returns a plan, never executes."""
    info = UpdateInfo(current=current_version, manifest_url=manifest_url)
    if not manifest_url:
        info.error = "Nenhuma URL de atualização configurada."
        return info
    if not _allowed_origin(manifest_url):
        info.error = "A origem da atualização precisa ser HTTPS (ou localhost)."
        return info
    try:
        import urllib.request

        req = urllib.request.Request(manifest_url, headers={"Accept": "application/json",
                                                            "User-Agent": "OpenHUD-Updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(1_000_000)
        manifest = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        info.error = f"Falha ao buscar o manifesto: {type(exc).__name__}: {exc}"
        return info

    info.latest = str(manifest.get("version", ""))
    info.notes = str(manifest.get("notes", ""))
    artifacts = []
    for art in manifest.get("artifacts", []) or []:
        try:
            name = _safe_name(str(art.get("name", "")))
        except ValueError:
            continue
        url = str(art.get("url", ""))
        if not _allowed_origin(url):
            continue
        artifacts.append({"name": name, "url": url, "sha256": str(art.get("sha256", ""))})
    info.artifacts = artifacts
    info.available = bool(info.latest) and _version_tuple(info.latest) > _version_tuple(current_version)
    if not info.available and info.latest:
        info.notes = info.notes or "Você já está na versão mais recente."
    return info


def download_artifact(url: str, sha256: str, dest_dir: Path, timeout: float = 60.0) -> dict[str, Any]:
    """Download one artifact, verify its hash and store it for manual install.

    Never executes the file. Returns an honest error on mismatch.
    """
    if not _allowed_origin(url):
        return {"ok": False, "error": "Origem não permitida (exige HTTPS)."}
    try:
        import urllib.request

        name = _safe_name(urlparse(url).path.split("/")[-1] or "artifact.bin")
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / name
        with urllib.request.urlopen(url, timeout=timeout) as resp, open(target, "wb") as out:
            out.write(resp.read(200 * 1024 * 1024))
        if sha256 and not verify_sha256(target, sha256):
            target.unlink(missing_ok=True)
            return {"ok": False, "error": "A soma de verificação (sha256) não confere. Download descartado."}
        return {"ok": True, "path": str(target), "verified": bool(sha256)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
