#!/usr/bin/env python3
"""Install the Windows build workflow into .github/workflows/.

The workflow file cannot always be pushed by every credential: GitHub refuses
to let a token without the ``workflow`` scope create or update files under
``.github/workflows/``. To keep the project pushable with a plain ``repo``
token, the workflow is kept as a template (``installer/github-actions/
windows-build.yml``) and copied into place by this script.

Run once, with a credential that has the ``workflow`` scope (or from the GitHub
web UI by pasting the same file):

    python installer/enable-github-build.py
    git add .github/workflows/windows-build.yml
    git commit -m "ci: enable Windows build"
    git push

It is idempotent: running it again only rewrites the destination if the content
differs.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "installer" / "github-actions" / "windows-build.yml"
DST = ROOT / ".github" / "workflows" / "windows-build.yml"


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    if not SRC.is_file():
        print(f"Template não encontrado: {SRC}")
        return 1
    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.is_file() and DST.read_bytes() == SRC.read_bytes():
        print(f"Já instalado e atualizado: {_display(DST)}")
        return 0
    shutil.copyfile(SRC, DST)
    print(f"Instalado: {_display(DST)}")
    print("\nPróximos passos:")
    print("  git add .github/workflows/windows-build.yml")
    print('  git commit -m "ci: enable Windows build"')
    print("  git push")
    print("\nObservação: o token de push precisa do escopo 'workflow'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
