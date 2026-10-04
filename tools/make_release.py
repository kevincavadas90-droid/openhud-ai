"""Build the release manifest for the Windows installer.

Run after compiling ``OpenHUD-AI-Setup.exe`` (on Windows) and copying it into
``dist/`` or ``installer/Output/``:

    python tools/make_release.py

It computes the real size and SHA-256 of the artifact and writes
``release.json`` next to it. The server reads this (or recomputes it from the
artifact) so the download page can display a verifiable hash. Nothing is
fabricated: if the file is missing, the command fails instead of guessing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openhud.core import release as rel  # noqa: E402


def main() -> int:
    artifact = rel._first_existing_artifact()
    if artifact is None:
        print("Nenhum instalador encontrado em dist/ ou installer/Output/.")
        print("Compile primeiro:  iscc installer\\openhud.iss  (no Windows)")
        return 1
    manifest = {
        "product": rel.PRODUCT,
        "version": rel.get_release().version,
        "platform": rel.PLATFORM,
        "filename": artifact.name,
        "size": artifact.stat().st_size,
        "size_human": rel.human_size(artifact.stat().st_size),
        "sha256": rel._sha256(artifact),
    }
    out = artifact.parent / "release.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\nManifesto escrito em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
