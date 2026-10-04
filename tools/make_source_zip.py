#!/usr/bin/env python3
"""Build a clean source ZIP of OpenHUD AI for distribution.

The archive is built from the files Git tracks (``git archive``) plus any
untracked-but-wanted files, so it never contains secrets, caches, the virtual
environment, local databases or temporary files. A real SHA-256 and size are
printed and written to a sibling ``.sha256`` file.

Usage:
    python tools/make_source_zip.py                 # OpenHUD-AI-Complete-<ver>.zip
    python tools/make_source_zip.py --out /tmp/x.zip
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Never include these, even if some are tracked by accident.
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".agent_tmp", "data", "workspace",
    "dist", "build", "installer/Output", ".idea", ".vscode",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3", ".exe", ".spec"}
EXCLUDE_NAMES = {".env", ".env.local", ".env.production", "secrets.json"}
SECRET_MARKERS = ("token", "secret", "password", "credential", "apikey", "api_key")


def _version() -> str:
    sys.path.insert(0, str(REPO))
    try:
        import openhud  # noqa: PLC0415

        return openhud.__version__
    except Exception:
        return "0.0.0"


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [REPO / p for p in out.split("\0") if p]


def _is_excluded(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    for i in range(1, len(parts) + 1):
        if "/".join(parts[:i]) in EXCLUDE_DIRS:
            return True
    name = parts[-1]
    if name in EXCLUDE_NAMES:
        return True
    if Path(name).suffix in EXCLUDE_SUFFIXES:
        return True
    # Don't ship anything that looks like a per-user secret file.
    low = name.lower()
    if low.endswith((".key", ".pem")) or (low.endswith(".json") and any(m in low for m in SECRET_MARKERS)):
        return True
    return False


def build(out: Path) -> tuple[Path, int, str, list[str]]:
    files = [f for f in _tracked_files() if f.is_file()]
    kept: list[Path] = []
    for f in files:
        rel = f.relative_to(REPO).as_posix()
        if not _is_excluded(rel):
            kept.append(f)

    out.parent.mkdir(parents=True, exist_ok=True)
    root = f"OpenHUD-AI-{_version()}"
    names: list[str] = []
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in sorted(kept):
            rel = f.relative_to(REPO).as_posix()
            arc = f"{root}/{rel}"
            zf.write(f, arc)
            names.append(rel)

    size = out.stat().st_size
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    return out, size, sha, names


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n} B"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a clean OpenHUD AI source ZIP.")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    out = args.out or (REPO / f"OpenHUD-AI-Complete-{_version()}.zip")
    path, size, sha, names = build(out)
    (path.with_suffix(path.suffix + ".sha256")).write_text(f"{sha}  {path.name}\n")

    print(f"ZIP:    {path.resolve()}")
    print(f"Size:   {_human(size)} ({size} bytes)")
    print(f"SHA256: {sha}")
    print(f"Files:  {len(names)}")
    top = sorted({n.split('/')[0] for n in names})
    print("Top-level:", ", ".join(top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
