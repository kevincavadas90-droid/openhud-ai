#!/usr/bin/env python3
"""Prepare the OpenHUD AI distribution bundle and manifest.

One command that finalizes everything a download page needs, and works on any
platform (including Linux CI):

    python tools/prepare_release.py

It:
  1. builds the clean source ZIP (``tools/make_source_zip.py`` logic);
  2. picks up the Windows installer if one was compiled into ``dist/`` or
     ``installer/Output/`` (never invents one);
  3. computes the real size and SHA-256 of each artifact;
  4. writes ``dist/release-manifest.json``;
  5. prints the exact commands to publish (GitHub Release) and the environment
     variables the server needs to show the real download button.

Nothing is fabricated: a missing installer is reported as missing, not guessed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openhud  # noqa: E402
from openhud.core import release as rel  # noqa: E402
from tools.make_source_zip import build as build_source_zip  # noqa: E402


def _artifact_entry(path: Path | None) -> dict | None:
    if path is None:
        return None
    return {
        "filename": path.name,
        "size": path.stat().st_size,
        "size_human": rel.human_size(path.stat().st_size),
        "sha256": rel._sha256(path),
        "path": str(path),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare the OpenHUD AI release bundle.")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "dist",
                    help="where to write the manifest and source ZIP (default: dist/)")
    args = ap.parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print("== OpenHUD AI — preparação do release ==")
    print(f"Versão: {openhud.__version__}\n")

    # 1. Source ZIP (always buildable).
    zip_path = out_dir / rel.SOURCE_ARTIFACT_NAME
    zip_path, size, sha, names = build_source_zip(zip_path)
    print(f"[1/4] Código-fonte: {zip_path.name} ({rel.human_size(size)}, {len(names)} arquivos)")

    # 2. Windows installer, only if it really exists.
    installer = rel._first_existing_artifact()
    if installer is not None:
        print(f"[2/4] Instalador encontrado: {installer}")
    else:
        print("[2/4] Instalador do Windows AUSENTE — compile no Windows "
              "(installer\\build-windows.ps1) e copie para dist/.")

    # 3. Manifest with real hashes.
    manifest = {
        "product": rel.PRODUCT,
        "version": openhud.__version__,
        "platform": rel.PLATFORM,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_zip": _artifact_entry(zip_path),
        "installer": _artifact_entry(installer),
    }
    manifest_path = out_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[3/4] Manifesto: {manifest_path}")

    # 4. Exact publishing instructions.
    print("[4/4] Próximos passos para publicar:\n")
    print("  Código-fonte (funciona já):")
    print(f"    - Anexe {zip_path.name} a uma GitHub Release (tag v{openhud.__version__}).")
    print("    - No servidor, defina:")
    print("        OPENHUD_SOURCE_URL=<url-do-zip>")
    print("      (ou OPENHUD_SERVE_SOURCE=1 para servir o arquivo localmente)\n")
    if installer is not None:
        print("  Instalador do Windows:")
        print(f"    - Anexe {installer.name} à mesma release.")
        print("    - No servidor, defina:")
        print("        OPENHUD_DOWNLOAD_URL=<url-do-exe>")
        print("      (ou OPENHUD_SERVE_INSTALLER=1 para servir localmente)\n")
    else:
        print("  Instalador do Windows: compile no Windows antes de publicar.\n")
    print("  Doação (opcional): OPENHUD_DONATION_URL=<url-de-doacao>\n")
    print("A página /download mostra o botão real assim que a URL for definida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
