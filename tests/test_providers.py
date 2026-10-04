"""Tests for the provider fallback chain and the auth layer.

Uses real local HTTP servers as providers so the fallback logic, transport
errors and reporting are exercised end to end (no mocks of our own code).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="openhud-prov-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")

from openhud.core.llm import ProviderConfig  # noqa: E402
from openhud.core.providers import (  # noqa: E402
    AllProvidersFailed,
    ProviderEntry,
    ProviderManager,
    build_provider_manager,
)
from openhud.web.auth import AuthManager  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    status = 200
    body: dict = {}

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length", 0)))
        data = json.dumps(type(self).body).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _serve(status: int, body: dict) -> tuple[ThreadingHTTPServer, str]:
    handler = type("H", (_Handler,), {"status": status, "body": body})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def _entry(name: str, base_url: str, priority: int) -> ProviderEntry:
    return ProviderEntry(
        name=name,
        label=name,
        priority=priority,
        config=ProviderConfig(provider="openai", model="m", base_url=base_url, api_key="k"),
    )


def test_fallback_uses_second_provider_when_first_fails():
    bad, bad_url = _serve(500, {"error": "boom"})
    good, good_url = _serve(200, {"choices": [{"message": {"content": "oi"}}]})
    try:
        manager = ProviderManager([_entry("bad", bad_url, 0), _entry("good", good_url, 1)])
        seen = []
        outcome = manager.chat([{"role": "user", "content": "x"}], on_attempt=seen.append)
        assert outcome.provider == "good"
        assert outcome.response.content == "oi"
        assert [a.provider for a in seen] == ["bad", "good"]
        assert seen[0].ok is False and seen[1].ok is True
    finally:
        bad.shutdown()
        good.shutdown()


def test_all_providers_failed_reports_every_attempt():
    bad1, url1 = _serve(500, {"error": "no"})
    bad2, url2 = _serve(500, {"error": "nope"})
    try:
        manager = ProviderManager([_entry("a", url1, 0), _entry("b", url2, 1)])
        try:
            manager.chat([{"role": "user", "content": "x"}])
            assert False, "expected AllProvidersFailed"
        except AllProvidersFailed as exc:
            assert {a.provider for a in exc.attempts} == {"a", "b"}
            assert "Groq" in str(exc)
    finally:
        bad1.shutdown()
        bad2.shutdown()


def test_keyless_selected_builds_chain_without_keys():
    manager = build_provider_manager(
        selected_provider="pollinations",
        model="openai",
        base_url="https://text.pollinations.ai/openai",
        temperature=0.7,
        max_tokens=256,
        supports_tools=True,
        secret_lookup=lambda name: None,  # no keys at all
        keyed_defaults={},
    )
    names = [e.name for e in manager.entries()]
    assert names[0] == "pollinations"
    # A local ollama fallback is always appended.
    assert "ollama" in names


def test_selected_provider_uses_user_base_url():
    manager = build_provider_manager(
        selected_provider="openai",
        model="custom-model",
        base_url="http://127.0.0.1:9999/v1",
        temperature=0.5,
        max_tokens=128,
        supports_tools=True,
        secret_lookup=lambda name: "key" if name == "openai" else None,
        keyed_defaults={
            "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
        },
    )
    first = manager.entries()[0]
    assert first.config.base_url == "http://127.0.0.1:9999/v1"
    assert first.config.model == "custom-model"
    assert first.config.api_key == "key"


def test_auth_password_and_session_token():
    auth = AuthManager(Path(_TMP) / "authdata")
    auth.enabled = True
    auth._password_hash = __import__("openhud.web.auth", fromlist=["hash_password"]).hash_password(
        "segredo", auth._salt
    )
    assert auth.verify_password("segredo") is True
    assert auth.verify_password("errado") is False

    token = auth.issue_token()
    assert auth.verify_token(token) is True
    assert auth.verify_token(token + "x") is False
    assert auth.verify_token("garbage") is False
    assert auth.verify_token(None) is False
