"""Release metadata for the OpenHUD AI Windows installer.

The download page must never invent a file, a size or a hash. This module
resolves the *real* installer metadata from one of three sources, in order:

1. an explicit hosting URL (``OPENHUD_DOWNLOAD_URL``) — the installer lives on
   GitHub Releases / a CDN and we only describe it;
2. a local build artifact (``dist/`` or ``installer/Output/``) — the .exe was
   compiled on Windows and copied here; we compute its real size and SHA-256;
3. nothing — the page reports ``published: false`` and explains what is missing.

Nothing here fabricates a download. ``sha256`` is computed from the actual file
with :func:`hashlib`; ``published`` is only true when a real URL was provided.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__

PRODUCT = "OpenHUD AI"
PLATFORM = "Windows 10 / 11 (64-bit)"
ARTIFACT_NAME = "OpenHUD-AI-Setup.exe"
LEGACY_ARTIFACT_NAMES = ("OpenHUD AI Setup.exe", "openhud-setup.exe")
SOURCE_ARTIFACT_NAME = f"OpenHUD-AI-Complete-{__version__}.zip"

# Where a real build would land if compiled on Windows and copied into the repo.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _artifact_dirs() -> tuple[str, ...]:
    # Read OPENHUD_RELEASE_DIR lazily so tests/operators can point at a build
    # directory without reloading the module.
    return (
        os.environ.get("OPENHUD_RELEASE_DIR", ""),
        str(_REPO_ROOT / "dist"),
        str(_REPO_ROOT / "installer" / "Output"),
    )

REQUIREMENTS = (
    "Windows 10 ou 11 (64 bits)",
    "4 GB de RAM (8 GB recomendado)",
    "200 MB livres em disco",
    "Conexão de internet (para falar com o servidor OpenHUD)",
    "Opcional: microfone para voz; permissões de tela/controle para o assistente",
)


def _first_existing_artifact() -> Path | None:
    for d in _artifact_dirs():
        if not d:
            continue
        base = Path(d)
        if not base.is_dir():
            continue
        for name in (ARTIFACT_NAME, *LEGACY_ARTIFACT_NAMES):
            candidate = base / name
            if candidate.is_file():
                return candidate
    return None


def _first_existing_source() -> Path | None:
    """Locate a real source ZIP, if one was generated (never invented)."""
    override = os.environ.get("OPENHUD_SOURCE_DIR", "").strip()
    dirs = (override,) if override else (_REPO_ROOT, *_artifact_dirs())
    for d in dirs:
        if not d:
            continue
        base = Path(d)
        if not base.is_dir():
            continue
        candidate = base / SOURCE_ARTIFACT_NAME
        if candidate.is_file():
            return candidate
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(num: int) -> str:
    if num <= 0:
        return "—"
    units = ("B", "KB", "MB", "GB")
    size = float(num)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{num} B"


@dataclass
class Release:
    product: str = PRODUCT
    version: str = __version__
    platform: str = PLATFORM
    filename: str = ARTIFACT_NAME
    url: str | None = None
    size: int = 0
    size_human: str = "—"
    sha256: str | None = None
    released_at: str | None = None
    requirements: list[str] = field(default_factory=lambda: list(REQUIREMENTS))
    min_windows: str = "Windows 10 (64-bit)"
    notes: str = ""
    published: bool = False
    source: str = "none"  # "url" | "artifact" | "none"
    serving: bool = False
    source_zip_name: str | None = None
    source_zip_size: int = 0
    source_zip_size_human: str = "—"
    source_zip_sha256: str | None = None
    source_zip_available: bool = False
    source_zip_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _released_at(path: Path | None) -> str | None:
    if path is not None:
        try:
            ts = path.stat().st_mtime
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except OSError:
            pass
    return None


def get_release() -> Release:
    """Resolve the current release description. Never raises."""
    rel = Release()
    artifact = _first_existing_artifact()
    if artifact is not None:
        rel.filename = artifact.name
        try:
            rel.size = artifact.stat().st_size
            rel.size_human = human_size(rel.size)
            rel.sha256 = _sha256(artifact)
            rel.released_at = _released_at(artifact)
            rel.source = "artifact"
        except OSError:
            pass

    # An explicit hosting URL always wins (GitHub Releases / CDN).
    url = os.environ.get("OPENHUD_DOWNLOAD_URL", "").strip()
    if url:
        rel.url = url
        rel.published = True
        if rel.source == "none":
            rel.source = "url"
        # If we do not have the local artifact, the URL's filename may differ.
        rel.filename = url.rsplit("/", 1)[-1].split("?")[0] or rel.filename

    # Opt-in: serve the local artifact from this app (fine for a small VPS,
    # not recommended on free PaaS — see DEPLOY.md).
    if os.environ.get("OPENHUD_SERVE_INSTALLER", "").lower() in {"1", "true", "on"} and artifact is not None:
        rel.serving = True
        rel.published = True
        if not rel.url:
            rel.url = "/download/file"
        rel.source = "artifact"

    # Source ZIP: describe it only when a real file exists (never invented).
    source_zip = _first_existing_source()
    if source_zip is not None:
        rel.source_zip_name = source_zip.name
        rel.source_zip_available = True
        try:
            rel.source_zip_size = source_zip.stat().st_size
            rel.source_zip_size_human = human_size(rel.source_zip_size)
            rel.source_zip_sha256 = _sha256(source_zip)
        except OSError:
            rel.source_zip_available = False
    src_url = os.environ.get("OPENHUD_SOURCE_URL", "").strip()
    if src_url:
        rel.source_zip_url = src_url
        rel.source_zip_available = True
        if not rel.source_zip_name:
            rel.source_zip_name = src_url.rsplit("/", 1)[-1].split("?")[0] or SOURCE_ARTIFACT_NAME
    elif source_zip is not None and os.environ.get("OPENHUD_SERVE_SOURCE", "").lower() in {"1", "true", "on"}:
        rel.source_zip_url = "/download/source"

    rel.notes = changelog_summary()
    return rel


def changelog() -> list[dict]:
    """Return the changelog as a list of {version, date, items}.

    Parsed from CHANGELOG.md when present; otherwise a built-in summary so the
    page is never empty. This is documentation, not a fabricated release.
    """
    path = _REPO_ROOT / "CHANGELOG.md"
    if path.is_file():
        try:
            return _parse_changelog(path.read_text(encoding="utf-8"))
        except OSError:
            pass
    return [{
        "version": __version__,
        "date": "",
        "items": [
            "Assistente de computador (modos faça-comigo e faça-por-mim).",
            "Visão de tela (captura + OCR), mouse, teclado e navegador.",
            "Níveis de autonomia e confirmação de ações sensíveis.",
            "Estados de tarefa com PARAR/PAUSAR e cancelamento por voz.",
            "Aplicativo Windows com bandeja, diagnóstico e pareamento.",
            "Backups, atualizações seguras e implantação em container.",
        ],
    }]


def _parse_changelog(text: str) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if current:
                entries.append(current)
            title = line[3:].strip()
            version, _, date = title.partition(" ")
            current = {"version": version.strip(), "date": date.strip("() "), "items": []}
        elif current is not None and line.lstrip().startswith(("- ", "* ")):
            current["items"].append(line.lstrip()[2:].strip())
    if current:
        entries.append(current)
    return entries or [{"version": __version__, "date": "", "items": ["Sem notas."]}]


def changelog_summary(limit: int = 4) -> str:
    entries = changelog()
    if not entries:
        return ""
    return "; ".join(entries[0]["items"][:limit])


def donation_url() -> str | None:
    """A real donation link, only when the operator configured one.

    The pricing page must never invent a payment address, so this returns
    ``None`` unless ``OPENHUD_DONATION_URL`` is set.
    """
    return os.environ.get("OPENHUD_DONATION_URL", "").strip() or None
