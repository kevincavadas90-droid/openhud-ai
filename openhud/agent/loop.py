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
from ..core.assist import (
    AUTONOMY_LEVELS,
    controller as task_controller,
    detect_control_phrase,
    gate,
    profile_guidance,
    autonomy_guidance,
)
from ..core.accessibility import from_settings as accessibility_from_settings
from ..core.context import build_context
from ..core.llm import LLMError
from ..core.modes import MODES
from ..core.personality import Personality
from ..core.providers import AllProvidersFailed, Attempt
from ..core.runtime import Runtime
from ..tools.assistant import CONTROL_TOOLS
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

    def _personality(self, settings: dict) -> Personality:
        traits = dict(settings.get("personality") or {})
        return Personality(
            traits={**Personality().traits, **traits},
            style=settings.get("personality_style", "natural"),
            adaptive=bool(settings.get("personality_adaptive", True)),
        )

    def _record_experience(self, user_text: str, result: str, success: bool) -> None:
        try:
            self.runtime.learning.record(
                action=user_text[:200], context="conversa", result=result, success=success,
            )
        except Exception:
            pass

    # Tools whose output is untrusted external content (web, files, plugins,
    # voice transcripts). Their output is sanitised and wrapped as data before
    # it reaches the model, so embedded instructions cannot override the prompt.
    _UNTRUSTED_TOOLS = {
        "web_search", "fetch_url", "http_request", "read_file", "list_files",
        "run_shell", "run_python", "analyze_data", "codex_analyze", "codex_test",
        "codex_sandbox", "pc_diagnose", "self_diagnose", "job_status",
    }

    def _safe_tool_text(self, tool_name: str, text: str) -> str:
        from ..core.sanitizer import detect, sanitize, wrap_untrusted

        cleaned = sanitize(text)
        if tool_name in self._UNTRUSTED_TOOLS:
            findings = detect(cleaned)
            if findings:
                self.runtime.db.add_activity(
                    "injection_warning", f"{tool_name}: {', '.join(findings)}",
                )
            return wrap_untrusted(cleaned, source=f"tool:{tool_name}")
        return cleaned

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
        level = settings.get("autonomy_level", "guide")

        if emit is None:
            def emit(kind: str, detail: str) -> None:  # noqa: E306
                db.add_activity(kind, detail, conversation_id)

        # The loop owns persistence of the user turn so that calling run()
        # directly (without the HTTP layer) still produces a full transcript.
        db.add_message(conversation_id, "user", user_text)

        # Immediate voice/text control commands (Part 15) short-circuit the turn.
        phrase = detect_control_phrase(user_text)
        if phrase == "cancel":
            task_controller.request_cancel(conversation_id)
            msg = "Tudo bem, parei. Quando quiser, é só me chamar."
            db.add_message(conversation_id, "assistant", msg)
            yield AgentEvent("task_state", {"state": "cancelled", "label": "CANCELADO"})
            yield AgentEvent("token", {"text": msg})
            yield AgentEvent("done", {"steps": 0, "cancelled": True})
            return
        if phrase == "pause":
            task_controller.request_pause(conversation_id, True)
            msg = "Pausado. Diga 'continue' quando quiser retomar."
            db.add_message(conversation_id, "assistant", msg)
            yield AgentEvent("task_state", {"state": "waiting_user", "label": "AGUARDANDO USUÁRIO"})
            yield AgentEvent("token", {"text": msg})
            yield AgentEvent("done", {"steps": 0, "paused": True})
            return

        # Assemble a bounded, relevant context (mode, personality, memory).
        ctx_info = build_context(
            db, user_text,
            selected_mode=settings.get("mode", "auto"),
            personality=self._personality(settings),
            learning=self.runtime.learning,
        )
        mode = MODES[ctx_info.mode]

        profile = settings.get("profile", "standard")
        a11y = accessibility_from_settings(settings)

        # Build message history for the model.
        history = db.list_messages(conversation_id)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.runtime.tool_summaries(),
                    app_settings.workspace_dir,
                    memories=ctx_info.memories,
                    mode_guidance=f"{mode.label}: {mode.description}\n{mode.guidance}".strip(),
                    personality_guidance=ctx_info.personality.guidance(),
                    profile_guidance=profile_guidance(profile, a11y),
                    autonomy_guidance=autonomy_guidance(level),
                    hints=ctx_info.hints,
                    experiences=ctx_info.experiences,
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

        manager = self.runtime.provider_manager()
        tool_specs = self.runtime.registry.specs(self.runtime.enabled_tool_names())
        ctx = self._context(conversation_id, emit)

        task_controller.begin(conversation_id)
        yield AgentEvent("task_state", {"state": "understanding", "label": "ENTENDENDO"})
        yield AgentEvent("activity", {"kind": "agent", "detail": "Iniciando execução"})
        yield AgentEvent("route", {"mode": ctx_info.mode, "label": mode.label,
                                   "icon": mode.icon, "family": mode.family,
                                   "profile": profile, "autonomy_level": level})

        for step in range(max_steps):
            if task_controller.is_cancelled(conversation_id):
                yield AgentEvent("task_state", {"state": "cancelled", "label": "CANCELADO"})
                self._record_experience(user_text, "cancelado pelo usuário", False)
                yield AgentEvent("done", {"steps": step, "cancelled": True})
                return
            if not task_controller.wait_if_paused(conversation_id):
                yield AgentEvent("task_state", {"state": "cancelled", "label": "CANCELADO"})
                yield AgentEvent("done", {"steps": step, "cancelled": True})
                return

            def report(attempt: Attempt) -> None:
                kind = "provider_ok" if attempt.ok else "provider_fail"
                db.add_activity(kind, f"{attempt.provider}: {attempt.detail}", conversation_id)

            try:
                outcome = manager.chat(messages, tools=tool_specs, on_attempt=report)
            except AllProvidersFailed as exc:
                db.add_activity("error", str(exc), conversation_id)
                self._record_experience(user_text, str(exc), False)
                yield AgentEvent("task_state", {"state": "error", "label": "ERRO", "detail": str(exc)})
                yield AgentEvent("error", {"message": str(exc)})
                return
            except LLMError as exc:
                db.add_activity("error", str(exc), conversation_id)
                self._record_experience(user_text, str(exc), False)
                yield AgentEvent("task_state", {"state": "error", "label": "ERRO", "detail": str(exc)})
                yield AgentEvent("error", {"message": str(exc)})
                return

            response = outcome.response
            yield AgentEvent("provider", {"provider": outcome.provider, "label": outcome.label})

            if response.usage:
                db.add_activity("usage", json.dumps(response.usage), conversation_id)

            if not response.tool_calls:
                content = response.content or "(sem resposta)"
                db.add_message(conversation_id, "assistant", content)
                self._record_experience(user_text, content, True)
                task_controller.finish(conversation_id, "done")
                yield AgentEvent("task_state", {"state": "done", "label": "CONCLUÍDO"})
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
                if task_controller.is_cancelled(conversation_id):
                    yield AgentEvent("task_state", {"state": "cancelled", "label": "CANCELADO"})
                    yield AgentEvent("done", {"steps": step, "cancelled": True})
                    return

                yield AgentEvent("tool_start", {"name": call.name, "arguments": call.arguments})

                tool = self.runtime.registry.get(call.name)
                decision = gate(
                    call.name, call.arguments, settings,
                    tool_is_control=call.name in CONTROL_TOOLS,
                    tool_requires_confirmation=bool(tool and tool.requires_confirmation),
                    legacy_autonomy=autonomy,
                )
                approved = True

                if decision["decision"] == "block":
                    result_text = decision["reason"]
                    db.add_activity("blocked", f"{call.name}: {decision['reason']}", conversation_id)
                    db.add_message(conversation_id, "tool", result_text,
                                   tool_calls={"tool_call_id": call.id, "name": call.name})
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})
                    yield AgentEvent("tool_result", {"name": call.name, "ok": False, "output": result_text})
                    yield AgentEvent("task_state", {"state": "waiting_user", "label": "AGUARDANDO USUÁRIO",
                                                    "detail": result_text})
                    continue

                if decision["decision"] == "confirm":
                    reason = decision["reason"]
                    yield AgentEvent("task_state", {"state": "waiting_confirmation",
                                                    "label": "AGUARDANDO CONFIRMAÇÃO", "detail": reason})
                    req = broker.create(call.name, call.arguments, reason=reason)
                    db.add_activity("confirmation", f"{call.name} aguardando aprovação: {reason}", conversation_id)
                    yield AgentEvent(
                        "confirmation",
                        {"request_id": req.request_id, "tool": call.name,
                         "arguments": call.arguments, "reason": reason,
                         "sensitive": decision.get("sensitive", False)},
                    )
                    approved = broker.wait(req)
                    if approved:
                        yield AgentEvent("task_state", {"state": "executing", "label": "EXECUTANDO"})
                elif decision["decision"] == "auto":
                    yield AgentEvent("task_state", {"state": "executing", "label": "EXECUTANDO",
                                                    "detail": call.name})

                if not approved:
                    result_text = "Ação recusada pelo usuário."
                    db.add_message(conversation_id, "tool", result_text,
                                   tool_calls={"tool_call_id": call.id, "name": call.name})
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})
                    yield AgentEvent("tool_result", {"name": call.name, "ok": False, "output": result_text})
                    continue

                result = self.runtime.registry.execute(call.name, call.arguments, ctx)
                safe_text = self._safe_tool_text(call.name, result.to_text())
                db.add_message(conversation_id, "tool", result.to_text(),
                               tool_calls={"tool_call_id": call.id, "name": call.name})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": safe_text})
                yield AgentEvent(
                    "tool_result",
                    {"name": call.name, "ok": result.ok, "output": result.output[:4000]},
                )

        final = f"Limite de {max_steps} etapas atingido sem resposta final."
        db.add_message(conversation_id, "assistant", final)
        task_controller.finish(conversation_id, "done")
        yield AgentEvent("task_state", {"state": "done", "label": "CONCLUÍDO"})
        yield AgentEvent("token", {"text": final})
        yield AgentEvent("done", {"steps": max_steps})
