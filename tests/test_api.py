"""HTTP-layer tests: REST endpoints and the SSE streaming turn.

Uses FastAPI's TestClient against a local mock LLM server, so the request
routing, persistence, streaming and confirmation flow are all real.
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

_TMP = tempfile.mkdtemp(prefix="openhud-api-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["OPENHUD_WORKSPACE"] = str(Path(_TMP) / "workspace")
os.environ["OPENHUD_PASSWORD"] = "test-password"

from fastapi.testclient import TestClient  # noqa: E402

from openhud.agent.confirm import broker  # noqa: E402
from openhud.core.runtime import runtime  # noqa: E402
from openhud.web.app import app  # noqa: E402

client = TestClient(app)
# The whole API is behind auth; establish a real session for the tests.
assert client.post("/api/login", json={"password": "test-password"}).status_code == 200


class MockLLM(BaseHTTPRequestHandler):
    calls = 0
    script: list[dict] = []

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length", 0)))
        i = min(MockLLM.calls, len(MockLLM.script) - 1)
        MockLLM.calls += 1
        data = json.dumps(MockLLM.script[i]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def start_mock(script):
    MockLLM.calls = 0
    MockLLM.script = script
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


FINAL = [{"choices": [{"message": {"role": "assistant", "content": "pronto"}, "finish_reason": "stop"}]}]


def test_health_and_settings_roundtrip():
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert "provider" in health and "configured" in health

    # The keyless provider needs no API key, so it is always configured.
    client.put("/api/settings", json={"provider": "pollinations", "model": "openai"})
    assert client.get("/api/health").json()["configured"] is True

    r = client.put("/api/settings", json={"provider": "ollama", "model": "llama3.1"})
    body = r.json()
    assert body["provider"] == "ollama"
    assert body["base_url"] == "http://localhost:11434/v1"
    client.put("/api/settings", json={"provider": "openai", "model": "gpt-4o-mini",
                                      "base_url": "https://api.openai.com/v1"})


def test_auth_required_and_rejected():
    anon = TestClient(app)
    assert anon.get("/api/settings").status_code == 401
    assert anon.post("/api/login", json={"password": "wrong"}).status_code == 401
    # A protected page redirects the browser to the login screen.
    page = anon.get("/app", follow_redirects=False)
    assert page.status_code == 302
    assert page.headers["location"] == "/login"


def test_secrets_never_return_full_value():
    client.post("/api/secrets", json={"name": "openai", "value": "sk-verysecretvalue123"})
    listing = client.get("/api/secrets").json()
    entry = next(s for s in listing if s["name"] == "openai")
    assert "verysecretvalue" not in entry["preview"]
    assert entry["preview"].startswith("sk-v")


def test_projects_conversations_messages():
    proj = client.post("/api/projects", json={"name": "Projeto X"}).json()
    conv = client.post("/api/conversations", json={"project_id": proj["id"]}).json()
    assert client.get(f"/api/conversations/{conv['id']}").json()["title"] == "Nova conversa"
    assert client.get(f"/api/conversations/{conv['id']}/messages").json() == []
    assert client.delete(f"/api/conversations/{conv['id']}").json()["deleted"] is True


def test_memory_crud():
    created = client.post("/api/memories", json={"content": "teste de memória", "tags": "t"}).json()
    assert any(m["id"] == created["id"] for m in client.get("/api/memories").json())
    client.put(f"/api/memories/{created['id']}", json={"content": "editado", "tags": "t2"})
    assert any(m["content"] == "editado" for m in client.get("/api/memories").json())
    assert client.delete(f"/api/memories/{created['id']}").json()["deleted"] is True


def test_file_sandbox_and_crud():
    assert client.post("/api/files", json={"path": "a/b.txt", "content": "oi"}).status_code == 200
    assert client.get("/api/files/content", params={"path": "a/b.txt"}).json()["content"] == "oi"
    assert client.get("/api/files", params={"path": "a"}).json()[0]["name"] == "b.txt"
    # Traversal is refused.
    assert client.get("/api/files/content", params={"path": "../../etc/passwd"}).status_code == 400


def test_streaming_turn_autonomous():
    server, base_url = start_mock(FINAL)
    try:
        runtime.secrets.set("openai", "k")
        runtime.update_settings({"provider": "openai", "model": "mock", "base_url": base_url,
                                 "autonomy": "autonomous", "max_steps": 4})
        conv = client.post("/api/conversations", json={}).json()
        events = []
        with client.stream("POST", f"/api/conversations/{conv['id']}/messages",
                           json={"text": "olá"}) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
        assert "done" in events
        msgs = client.get(f"/api/conversations/{conv['id']}/messages").json()
        assert [m["role"] for m in msgs] == ["user", "assistant"]
    finally:
        server.shutdown()


def test_tasks_api_crud():
    assert client.post("/api/tasks", json={"name": "x", "prompt": "y", "interval_seconds": 5}).status_code == 400
    created = client.post("/api/tasks", json={"name": "relatorio", "prompt": "gere um resumo",
                                              "interval_seconds": 120}).json()
    assert created["enabled"] == 1
    assert any(t["id"] == created["id"] for t in client.get("/api/tasks").json())
    assert client.put(f"/api/tasks/{created['id']}", json={"enabled": False}).json()["enabled"] is False
    assert client.delete(f"/api/tasks/{created['id']}").json()["deleted"] is True


def test_confirmation_endpoint_resolves_pending():
    """The HTTP confirm endpoint resolves a real broker request."""
    req = broker.create("run_python", {"code": "print(1)"})
    resp = client.post(f"/api/confirmations/{req.request_id}", json={"approved": True})
    assert resp.json() == {"resolved": True, "approved": True}
    assert broker.wait(req, timeout=1) is True


def test_streaming_turn_with_tool_and_confirmation():
    """Supervised mode pauses on the tool and proceeds once approved.

    The confirmation is resolved from a helper thread because TestClient
    serializes requests through a single portal; a real uvicorn server
    handles the concurrent request natively.
    """
    script = [
        {"choices": [{"message": {"role": "assistant", "content": "vou rodar",
                                  "tool_calls": [{"id": "c1", "type": "function",
                                                  "function": {"name": "run_python",
                                                               "arguments": json.dumps({"code": "print('ok-tool')"})}}]},
                      "finish_reason": "tool_calls"}]},
        {"choices": [{"message": {"role": "assistant", "content": "feito"}, "finish_reason": "stop"}]},
    ]
    server, base_url = start_mock(script)
    try:
        runtime.secrets.set("openai", "k")
        runtime.update_settings({"provider": "openai", "model": "mock", "base_url": base_url,
                                 "autonomy": "supervised", "max_steps": 4})
        conv = client.post("/api/conversations", json={}).json()

        stop = threading.Event()

        def approver():
            while not stop.is_set():
                for pending in broker.list_pending():
                    broker.resolve(pending["request_id"], True)
                stop.wait(0.05)

        helper = threading.Thread(target=approver, daemon=True)
        helper.start()

        events = []
        with client.stream("POST", f"/api/conversations/{conv['id']}/messages",
                           json={"text": "rode python"}) as resp:
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
        stop.set()
        assert "confirmation" in events
        assert "tool_result" in events
        assert "done" in events
    finally:
        server.shutdown()
