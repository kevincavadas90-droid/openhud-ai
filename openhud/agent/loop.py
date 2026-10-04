"""The agent execution loop.

Given a conversation, it repeatedly asks the LLM for the next action. When
the model requests tools, they are executed (with confirmation gating in
supervised mode) and the results are fed back until the model produces a
final answer or the step ceiling is reached.

The loop is a generator of :class:`AgentEvent` objects, which the API layer
streams to the UI. It performs blocking I/O; callers run it in a worker
thread.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..config import settings as app_settings
from ..core.llm import LLMError
from ..core.runtime import Runtime
from ..tools.base import ToolContext
from .confirm import broker
from .prompts import build_system_prompt


@dataclass
class AgentEvent:
    type: str  # token | tool_start | tool_result | confirmation | error | done | activity
    data: dict[str, Any] = field(default_factory=dict)


class Agent:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def _context(self, conversation_id: str | None, emit) -> ToolContext:
        s = self.runtime.get_settings()
        return ToolContext(
            workspace_dir=app_settings.workspace_dir,
            settings=app_settings,
            secrets=self.runtime.secrets,
            db=self.runtime.db,
            conversation_id=conversation_id,
            autonomy=s.get("autonomy", "supervised"),
            allow_network=bool(s.get("allow_network", True)),
            emit=emit,
        )

    def run(
        self,
        conversation_id: str,
        user_text: str,
        emit=None,
    ) -> Iterator[AgentEvent]:
        """Yield events for one user turn. Persists messages as it goes."""
        db = self.runtime.db
        settings = self.runtime.get_settings()
        autonomy = settings.get("autonomy", "supervised")
        max_steps = int(settings.get("max_steps", 25))

        if emit is None:
            def emit(kind: str, detail: str) -> None:  # noqa: E306
                db.add_activity(kind, detail, conversation_id)

        # The loop owns persistence of the user turn so that calling run()
        # directly (without the HTTP layer) still produces a full transcript.
        db.add_message(conversation_id, "user", user_text)

        # Build message history for the model.
        history = db.list_messages(conversation_id)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.runtime.tool_summaries(),
                    app_settings.workspace_dir,
                    memories=db.search_memories(user_text, limit=6),
                ),
            }
        ]
        for m in history:
            if m["role"] == "tool":
                meta = m.get("tool_calls") or {}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": meta.get("tool_call_id"),
                        "content": m["content"],
                    }
                )
                continue
            entry: dict[str, Any] = {"role": m["role"], "content": m["content"]}
            if m["role"] == "assistant" and m.get("tool_calls"):
                entry["tool_calls"] = m["tool_calls"]
            messages.append(entry)

        client = self.runtime.llm_client()
        tool_specs = self.runtime.registry.specs(self.runtime.enabled_tool_names())
        ctx = self._context(conversation_id, emit)

        yield AgentEvent("activity", {"kind": "agent", "detail": "Iniciando execução"})

        for step in range(max_steps):
            try:
                response = client.chat(messages, tools=tool_specs)
            except LLMError as exc:
                db.add_activity("error", str(exc), conversation_id)
                yield AgentEvent("error", {"message": str(exc)})
                return

            if response.usage:
                db.add_activity("usage", json.dumps(response.usage), conversation_id)

            if not response.tool_calls:
                content = response.content or "(sem resposta)"
                db.add_message(conversation_id, "assistant", content)
                yield AgentEvent("token", {"text": content})
                yield AgentEvent("done", {"steps": step + 1})
                return

            # Persist and stream the assistant's reasoning + tool calls.
            if response.content:
                yield AgentEvent("token", {"text": response.content})
            call_records = [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls
            ]
            db.add_message(conversation_id, "assistant", response.content, tool_calls=call_records)
            messages.append({"role": "assistant", "content": response.content, "tool_calls": call_records})

            for call in response.tool_calls:
                yield AgentEvent("tool_start", {"name": call.name, "arguments": call.arguments})

                tool = self.runtime.registry.get(call.name)
                approved = True
                if tool and tool.requires_confirmation and autonomy != "autonomous":
                    req = broker.create(call.name, call.arguments)
                    db.add_activity("confirmation", f"{call.name} aguardando aprovação", conversation_id)
                    yield AgentEvent(
                        "confirmation",
                        {"request_id": req.request_id, "tool": call.name, "arguments": call.arguments},
                    )
                    approved = broker.wait(req)
                elif tool and tool.requires_confirmation and autonomy == "autonomous":
                    db.add_activity("auto_approve", f"{call.name} auto-aprovado (modo autônomo)", conversation_id)

                if not approved:
                    result_text = "Ação recusada pelo usuário."
                    db.add_message(conversation_id, "tool", result_text,
                                   tool_calls={"tool_call_id": call.id, "name": call.name})
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})
                    yield AgentEvent("tool_result", {"name": call.name, "ok": False, "output": result_text})
                    continue

                result = self.runtime.registry.execute(call.name, call.arguments, ctx)
                db.add_message(conversation_id, "tool", result.to_text(),
                               tool_calls={"tool_call_id": call.id, "name": call.name})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result.to_text()})
                yield AgentEvent(
                    "tool_result",
                    {"name": call.name, "ok": result.ok, "output": result.output[:4000]},
                )

        final = f"Limite de {max_steps} etapas atingido sem resposta final."
        db.add_message(conversation_id, "assistant", final)
        yield AgentEvent("token", {"text": final})
        yield AgentEvent("done", {"steps": max_steps})
