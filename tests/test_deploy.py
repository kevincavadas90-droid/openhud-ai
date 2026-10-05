"""Tests for the public-hosting / deployment kit and opt-in CORS.

These exercise real code paths: the CORS middleware is verified by importing
the app in a subprocess with ``OPENHUD_CORS_ORIGINS`` set (the app builds its
middleware stack at import time), and the release-prep tool is run for real and
its manifest inspected. Nothing is mocked.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _run(env_extra: dict[str, str], code: str, tmp: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "OPENHUD_DATA_DIR": str(tmp / "data"),
        "OPENHUD_WORKSPACE": str(tmp / "workspace"),
        "OPENHUD_PASSWORD": "test-password",
    })
    env.update(env_extra)
    return subprocess.run(
        [PY, "-c", code], cwd=str(ROOT), env=env,
        capture_output=True, text=True, timeout=120,
    )


_CORS_PROBE = """
import os
from fastapi.testclient import TestClient
from openhud.web.app import app
c = TestClient(app)
allowed = os.environ.get("PROBE_ORIGIN", "")
r = c.get("/health", headers={"Origin": allowed})
print("ACAO=" + str(r.headers.get("access-control-allow-origin")))
r2 = c.get("/health", headers={"Origin": "https://evil.example"})
print("EVIL=" + str(r2.headers.get("access-control-allow-origin")))
"""


def test_cors_disabled_by_default(tmp_path):
    proc = _run({"PROBE_ORIGIN": "https://app.example.com"}, _CORS_PROBE, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "ACAO=None" in proc.stdout
    assert "EVIL=None" in proc.stdout


def test_cors_allowlist_enables_only_listed_origin(tmp_path):
    proc = _run(
        {
            "OPENHUD_CORS_ORIGINS": "https://app.example.com, https://other.example.com",
            "PROBE_ORIGIN": "https://app.example.com",
        },
        _CORS_PROBE, tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ACAO=https://app.example.com" in proc.stdout
    assert "EVIL=None" in proc.stdout


def test_prepare_release_builds_real_manifest(tmp_path):
    out = tmp_path / "dist"
    proc = subprocess.run(
        [PY, "tools/prepare_release.py", "--out-dir", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads((out / "release-manifest.json").read_text(encoding="utf-8"))
    import hashlib

    src = manifest["source_zip"]
    assert src is not None
    zip_path = out / src["filename"]
    assert zip_path.is_file()
    assert src["size"] == zip_path.stat().st_size
    assert src["sha256"] == hashlib.sha256(zip_path.read_bytes()).hexdigest()
    # The manifest must not invent a Windows installer that was never built.
    assert manifest["installer"] is None or Path(manifest["installer"]["path"]).is_file()


def test_source_zip_excludes_secrets_and_venv(tmp_path):
    out = tmp_path / "dist"
    subprocess.run(
        [PY, "tools/prepare_release.py", "--out-dir", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300, check=True,
    )
    import zipfile

    zip_path = next(out.glob("*.zip"))
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    joined = "\n".join(names)
    assert ".venv" not in joined
    assert "data/openhud.db" not in joined
    assert ".env" not in [Path(n).name for n in names]
    assert any(n.endswith("openhud/web/app.py") for n in names)


@pytest.mark.parametrize("name", [
    "Dockerfile", "fly.toml", "render.yaml", "railway.json",
    ".dockerignore", ".env.example", "DEPLOY.md",
])
def test_deploy_kit_files_present(name):
    assert (ROOT / name).is_file()


def test_fly_config_targets_internal_port_and_data_volume():
    text = (ROOT / "fly.toml").read_text(encoding="utf-8")
    assert "internal_port" in text
    assert "OPENHUD_HOST" in text
    assert "[mounts]" in text


def test_render_blueprint_uses_health_and_documents_persistence():
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "healthCheckPath: /health" in text
    assert "OPENHUD_DATA_DIR" in text
    # Free tier has no disk, so the blueprint must steer users to external DB.
    assert "OPENHUD_DATABASE_URL" in text


def test_dockerfile_sets_safe_defaults():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.13" in text
    assert "OPENHUD_HOST=0.0.0.0" in text
    assert "/data" in text


def test_publish_script_dry_run_is_honest(tmp_path):
    """The publish helper must not claim success without a token, and must run
    its release prep for real."""
    env = dict(os.environ)
    env.pop("GITHUB_TOKEN", None)
    proc = subprocess.run(
        [PY, "tools/publish_release.py", "--repo", "owner/name", "--dry-run"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 1
    assert "GITHUB_TOKEN" in proc.stdout
