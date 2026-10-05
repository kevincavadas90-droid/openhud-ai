#!/usr/bin/env python3
"""Publish OpenHUD AI: create the repo, push, and cut a release.

This is the one command that takes the project from a local checkout to a
public GitHub repository with a tagged release and downloadable assets. It is
honest about permissions: if the ``GITHUB_TOKEN`` cannot create repositories
(some integration tokens cannot), it stops and tells you exactly what to do.

Usage:
    python tools/publish_release.py --repo <owner>/<name>
    python tools/publish_release.py --repo kevincavadas90-droid/openhud-ai --dry-run

What it does (in order):
    1. runs tools/prepare_release.py to build the source ZIP + manifest;
    2. ensures the GitHub repository exists (creates it if the token allows);
    3. pushes the current branch (default: master);
    4. creates/updates the git tag v<version> and a GitHub Release;
    5. uploads the source ZIP (and the Windows installer, if compiled);
    6. prints the environment variables to set on the hosting platform.

Nothing is fabricated: a missing installer is skipped, not invented.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openhud  # noqa: E402


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(ROOT), text=True, **kw)


def _api(method: str, path: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"https://api.github.com{path}", data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "openhud-publish",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def _ensure_repo(repo: str, token: str, dry: bool) -> bool:
    owner, _, name = repo.partition("/")
    status, _ = _api("GET", f"/repos/{repo}", token)
    if status == 200:
        print(f"[repo] já existe: https://github.com/{repo}")
        return True
    if dry:
        print(f"[repo] (dry-run) criaria {repo}")
        return True
    print(f"[repo] criando {repo}…")
    status, body = _api("POST", "/user/repos", token, {
        "name": name,
        "description": "OpenHUD AI — assistente multifuncional para o seu computador.",
        "private": False,
        "has_issues": True,
        "has_wiki": False,
    })
    if status in (200, 201):
        print(f"[repo] criado: https://github.com/{repo}")
        return True
    print(f"[repo] NÃO foi possível criar ({status}: {body.get('message', '?')}).")
    print("       O token não tem permissão de criar repositórios.")
    print("       Crie o repositório manualmente em https://github.com/new")
    print("       e rode este script de novo (ele fará push e a release).")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish OpenHUD AI to GitHub + cut a release.")
    ap.add_argument("--repo", required=True, help="owner/name on GitHub")
    ap.add_argument("--branch", default="master")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("GITHUB_TOKEN não está definido. Configure-o e rode de novo.")
        return 1

    version = openhud.__version__
    tag = f"v{version}"
    print(f"== Publicar OpenHUD AI {version} em {args.repo} ==\n")

    # 1. Build the release bundle (source ZIP + manifest).
    prep = _run([sys.executable, "tools/prepare_release.py"], capture_output=True)
    if prep.returncode != 0:
        print(prep.stdout)
        print(prep.stderr, file=sys.stderr)
        return 1
    print(prep.stdout.strip().splitlines()[0])

    manifest_path = ROOT / "dist" / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets: list[Path] = []
    if manifest.get("source_zip"):
        assets.append(ROOT / "dist" / manifest["source_zip"]["filename"])
    if manifest.get("installer"):
        assets.append(Path(manifest["installer"]["path"]))
    print(f"[assets] {len(assets)} arquivo(s): " + ", ".join(a.name for a in assets))

    # 2. Repository.
    if not _ensure_repo(args.repo, token, args.dry_run):
        return 2

    remote_url = f"https://x-access-token:{token}@github.com/{args.repo}.git"
    if args.dry_run:
        print(f"[git] (dry-run) push {args.branch} e tag {tag}; upload de {len(assets)} asset(s).")
        return 0

    # 3. Push branch.
    existing = _run(["git", "remote", "get-url", "origin"], capture_output=True)
    if existing.returncode == 0:
        _run(["git", "remote", "set-url", "origin", remote_url])
    else:
        _run(["git", "remote", "add", "origin", remote_url])
    push = _run(["git", "push", "-u", "origin", args.branch], capture_output=True)
    print("[git] push:", (push.stdout + push.stderr).strip().splitlines()[-1] if (push.stdout + push.stderr).strip() else "ok")
    if push.returncode != 0:
        print(push.stderr)
        return 3

    # 4. Tag + release via the API (create release creates the tag too).
    status, body = _api("GET", f"/repos/{args.repo}/releases/tags/{tag}", token)
    if status == 200:
        print(f"[release] {tag} já existe (id {body.get('id')}).")
        release_id = body["id"]
    else:
        status, body = _api("POST", f"/repos/{args.repo}/releases", token, {
            "tag_name": tag,
            "target_commitish": args.branch,
            "name": f"OpenHUD AI {version}",
            "body": "Release automática do OpenHUD AI.\n\n"
                    "Ativos: código-fonte (.zip) e, quando disponível, o instalador do Windows (.exe).",
            "draft": False,
            "prerelease": False,
        })
        if status not in (200, 201):
            print(f"[release] falhou ({status}: {body.get('message', '?')}).")
            return 4
        release_id = body["id"]
        print(f"[release] criada {tag}.")

    # 5. Upload assets.
    import urllib.request

    for asset in assets:
        name = asset.name
        with asset.open("rb") as fh:
            data = fh.read()
        req = urllib.request.Request(
            f"https://uploads.github.com/repos/{args.repo}/releases/{release_id}/assets?name={name}",
            data=data, method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "User-Agent": "openhud-publish",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                ok = resp.status in (200, 201)
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"[asset] {name}: erro {e}")
        if ok:
            print(f"[asset] enviado: {name}")

    base = f"https://github.com/{args.repo}/releases/download/{tag}"
    print("\n== Pronto ==")
    print(f"Repositório: https://github.com/{args.repo}")
    print(f"Release:     https://github.com/{args.repo}/releases/tag/{tag}\n")
    print("Defina no servidor de hospedagem:")
    print(f"  OPENHUD_SOURCE_URL={base}/{manifest['source_zip']['filename']}")
    if manifest.get("installer"):
        print(f"  OPENHUD_DOWNLOAD_URL={base}/{manifest['installer']['filename']}")
    else:
        print("  # OPENHUD_DOWNLOAD_URL=...  (compile o instalador no Windows primeiro)")
    print("  OPENHUD_PUBLIC_URL=https://SEU-DOMINIO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
