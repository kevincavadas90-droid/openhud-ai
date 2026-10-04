"""Integration test for the agent loop.

The LLM is an external service, so a local HTTP server speaks the
OpenAI-compatible protocol. Everything else (agent loop, tool registry,
tool execution, persistence, confirmation broker) is the real code path.
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

_TMP = tempfile.mkdtemp(prefix="openhud-agent-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["OPENHUD_WORKSPACE"] = str(Path(_TMP) / "workspace")

from openhud.agent.confirm import broker  # noqa: E402
from openhud.agent.loop import Agent  # noqa: E402
from openhud.core.runtime import runtime  # noqa: E402


class MockLLMHandler(BaseHTTPRequestHandler):
    calls = 0
    script: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        self.rfile.read(length)
        index = min(MockLLMHandler.calls, len(MockLLMHandler.script) - 1)
        payload = MockLLMHandler.script[index]
        MockLLMHandler.calls += 1
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silence
        pass


def _start_mock(script: list[dict]) -> tuple[ThreadingHTTPServer, str]:
    MockLLMHandler.calls = 0
    MockLLMHandler.script = script
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockLLMHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/v1"


def _configure(base_url: str, autonomy: str) -> None:
    runtime.secrets.set("openai", "test-key")
    runtime.update_settings(
        {
            "provider": "openai",
            "model": "mock-model",
            "base_url": base_url,
            "autonomy": autonomy,
            "max_steps": 6,
            "enabled_tools": [],
        }
    )


TOOL_THEN_FINAL = [
    {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Vou calcular isso.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "run_python", "arguments": json.dumps({"code": "print(21*2)"})},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    },
    {"choices": [{"message": {"role": "assistant", "content": "O resultado é 42."}, "finish_reason": "stop"}]},
]


def test_agent_loop_autonomous_executes_tool():
    server, base_url = _start_mock(TOOL_THEN_FINAL)
    try:
        _configure(base_url, "autonomous")
        conv = runtime.db.create_conversation(title="loop")
        agent = Agent(runtime)
        events = list(agent.run(conv["id"], "quanto é 21*2?"))

        types = [e.type for e in events]
        assert "tool_start" in types
        assert "tool_result" in types
        assert "done" in types

        result = next(e for e in events if e.type == "tool_result")
        assert result.data["ok"] is True
        assert "42" in result.data["output"]

        final = next(e for e in events if e.type == "token" and "42" in e.data.get("text", ""))
        assert final.data["text"] == "O resultado é 42."

        roles = [m["role"] for m in runtime.db.list_messages(conv["id"])]
        assert "user" in roles and "assistant" in roles and "tool" in roles
    finally:
        server.shutdown()


def test_agent_loop_supervised_waits_for_confirmation():
    server, base_url = _start_mock(TOOL_THEN_FINAL)
    try:
        _configure(base_url, "supervised")
        conv = runtime.db.create_conversation(title="conf")
        agent = Agent(runtime)

        seen = {"confirm": None}
        collected = []

        def consume():
            for ev in agent.run(conv["id"], "quanto é 21*2?"):
                collected.append(ev)
                if ev.type == "confirmation" and seen["confirm"] is None:
                    seen["confirm"] = ev.data["request_id"]
                    broker.resolve(ev.data["request_id"], True)

        thread = threading.Thread(target=consume)
        thread.start()
        thread.join(timeout=30)

        assert seen["confirm"], "confirmation event was not emitted"
        result = next(e for e in collected if e.type == "tool_result")
        assert result.data["ok"] is True
        assert "42" in result.data["output"]
    finally:
        server.shutdown()


def test_agent_loop_denied_tool_is_reported():
    server, base_url = _start_mock(TOOL_THEN_FINAL)
    try:
        _configure(base_url, "supervised")
        conv = runtime.db.create_conversation(title="deny")
        agent = Agent(runtime)
        collected = []

        def consume():
            for ev in agent.run(conv["id"], "quanto é 21*2?"):
                collected.append(ev)
                if ev.type == "confirmation":
                    broker.resolve(ev.data["request_id"], False)

        thread = threading.Thread(target=consume)
        thread.start()
        thread.join(timeout=30)

        result = next(e for e in collected if e.type == "tool_result")
        assert result.data["ok"] is False
        assert "recusada" in result.data["output"].lower()
    finally:
        server.shutdown()
