"""Computer-assistant policy: user profiles, autonomy levels, task states,
sensitive-action classification and immediate cancellation.

This module is deliberately pure and framework-free so the behaviour can be
tested directly. It answers four questions the agent loop needs:

* Which profile is the user running under, and how should that change the
  explanation style? (:func:`profile_guidance`)
* How much may the assistant do on its own right now? (:func:`gate`)
* Which action is "sensitive" and must never run silently?
  (:func:`classify_action`)
* Has the user cancelled/paused the current task? (:class:`TaskController`)

Nothing here grants permissions by itself; it only narrows what the existing
MT5/PC permission gates already allow.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# user profiles
# --------------------------------------------------------------------------
PROFILES: dict[str, dict[str, Any]] = {
    "standard": {
        "label": "Padrão",
        "description": "Equilíbrio entre objetividade e detalhe.",
        "language_level": "normal",
        "explain_steps": False,
        "confirm_important": True,
    },
    "beginner": {
        "label": "Iniciante",
        "description": "Linguagem simples, passos curtos e paciência.",
        "language_level": "simple",
        "explain_steps": True,
        "confirm_important": True,
    },
    "power_user": {
        "label": "Avançado",
        "description": "Respostas diretas, menos explicação básica.",
        "language_level": "technical",
        "explain_steps": False,
        "confirm_important": False,
    },
    "accessibility": {
        "label": "Acessibilidade",
        "description": "Linguagem simples, instruções claras e voz calma.",
        "language_level": "simple",
        "explain_steps": True,
        "confirm_important": True,
        "calm_voice": True,
    },
}

DEFAULT_PROFILE = "standard"

# --------------------------------------------------------------------------
# autonomy levels (Part 5)
# --------------------------------------------------------------------------
AUTONOMY_LEVELS: dict[str, dict[str, Any]] = {
    "observe": {
        "level": 1, "label": "Observar",
        "description": "A IA apenas observa e analisa a tela. Não controla nada.",
        "can_control": False,
    },
    "guide": {
        "level": 2, "label": "Guiar",
        "description": "A IA mostra onde clicar e explica o procedimento; você executa.",
        "can_control": False,
    },
    "assisted": {
        "level": 3, "label": "Assistido",
        "description": "A IA pode executar ações simples depois da sua autorização.",
        "can_control": True, "always_confirm": True,
    },
    "automatic": {
        "level": 4, "label": "Automático",
        "description": "A IA conclui tarefas autorizadas; ações sensíveis ainda pedem confirmação.",
        "can_control": True, "always_confirm": False,
    },
}

DEFAULT_AUTONOMY_LEVEL = "guide"

# --------------------------------------------------------------------------
# task states (Part 14)
# --------------------------------------------------------------------------
TASK_STATES = [
    "observing", "understanding", "waiting_user", "executing",
    "waiting_confirmation", "done", "error", "cancelled",
]

TASK_STATE_LABELS: dict[str, str] = {
    "observing": "OBSERVANDO",
    "understanding": "ENTENDENDO",
    "waiting_user": "AGUARDANDO USUÁRIO",
    "executing": "EXECUTANDO",
    "waiting_confirmation": "AGUARDANDO CONFIRMAÇÃO",
    "done": "CONCLUÍDO",
    "error": "ERRO",
    "cancelled": "CANCELADO",
}

# --------------------------------------------------------------------------
# sensitive actions (Part 6) — must never run silently
# --------------------------------------------------------------------------
# Each rule: (category id, human label, keywords that indicate the action).
SENSITIVE_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("payment", "Pagamento ou transferência",
     ("pagamento", "pagar", "transferência", "transferencia", "pix", "boleto",
      "cartão de crédito", "cartao de credito", "checkout", "comprar", "compra",
      "assinar plano", "pagamento", "payment", "checkout", "purchase")),
    ("password", "Alteração de senha",
     ("alterar senha", "trocar senha", "mudar senha", "redefinir senha",
      "reset password", "change password")),
    ("delete", "Exclusão de dados",
     ("excluir", "apagar", "deletar", "remover permanentemente", "formatar",
      "delete permanently", "erase")),
    ("send_message", "Envio de mensagem",
     ("enviar mensagem", "enviar e-mail", "enviar email", "mandar mensagem",
      "publicar", "postar", "twittar", "enviar para todos")),
    ("send_document", "Envio de documento",
     ("enviar documento", "enviar arquivo", "compartilhar documento",
      "upload", "anexar e enviar")),
    ("install", "Instalação de programa",
     ("instalar", "instalar programa", "executar instalador", "setup.exe",
      "install")),
    ("run_file", "Execução de arquivo",
     ("executar arquivo", "rodar .exe", "abrir .exe", "executar .bat",
      "run exe")),
    ("system_change", "Alteração crítica do Windows",
     ("registro do windows", "regedit", "variável de ambiente do sistema",
      "desativar antivírus", "firewall", "serviço do windows", "system32",
      "desabilitar atualizações")),
    ("bank", "Ação bancária ou financeira",
     ("banco", "conta bancária", "conta bancaria", "investir", "aplicação financeira",
      "empréstimo", "emprestimo", "financiamento")),
]

# Tools whose mere use implies a sensitive category regardless of arguments.
# These are never auto-approved, even in autonomous mode. Ordinary tools that
# already require confirmation (run_shell, run_python, write_file) are NOT
# listed here: they keep the normal confirmation semantics so that autonomous
# work is not blocked. Text-based detection is applied to control tools only,
# to avoid false positives on code/file contents.
TOOL_SENSITIVITY: dict[str, str] = {
    "trading_execute_order": "bank",
    "delete_file": "delete",
}


@dataclass
class ActionClassification:
    sensitive: bool
    category: str = ""
    label: str = ""
    reason: str = ""
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensitive": self.sensitive, "category": self.category,
            "label": self.label, "reason": self.reason, "keywords": self.keywords,
        }


def _flatten(args: Any) -> str:
    if isinstance(args, dict):
        return " ".join(_flatten(v) for v in args.values())
    if isinstance(args, (list, tuple)):
        return " ".join(_flatten(v) for v in args)
    return str(args or "")


def classify_action(tool_name: str, args: dict[str, Any], text_scan: bool = True) -> ActionClassification:
    """Decide whether an action is sensitive and must be confirmed.

    ``text_scan=False`` skips the free-text keyword scan (used for ordinary
    tools whose arguments are code/content and would cause false positives).
    """
    if tool_name in TOOL_SENSITIVITY:
        cat = TOOL_SENSITIVITY[tool_name]
        label = next((lbl for c, lbl, _ in SENSITIVE_RULES if c == cat), cat)
        return ActionClassification(True, cat, label,
                                    f"A ferramenta '{tool_name}' pode alterar o sistema.",
                                    [tool_name])
    if not text_scan:
        return ActionClassification(False)
    text = _flatten(args).lower()
    for cat, label, keywords in SENSITIVE_RULES:
        hits = [k for k in keywords if k in text]
        if hits:
            return ActionClassification(True, cat, label,
                                        f"A ação menciona: {', '.join(hits[:3])}.", hits)
    return ActionClassification(False)


# --------------------------------------------------------------------------
# gate: may the assistant act, and does it need confirmation?
# --------------------------------------------------------------------------
def gate(tool_name: str, args: dict[str, Any], settings: dict[str, Any],
         tool_is_control: bool, tool_requires_confirmation: bool,
         legacy_autonomy: str) -> dict[str, Any]:
    """Return the decision for executing ``tool_name``.

    Result keys: ``decision`` in {"auto", "confirm", "block"} and ``reason``.
    """
    level = settings.get("autonomy_level", DEFAULT_AUTONOMY_LEVEL)
    if level not in AUTONOMY_LEVELS:
        level = DEFAULT_AUTONOMY_LEVEL
    info = AUTONOMY_LEVELS[level]

    # Text-based keyword scanning is only meaningful for computer-control
    # actions (opening URLs, typing, clicking). For ordinary tools the
    # arguments are code/content, so we rely on the tool's own confirmation
    # flag plus the always-sensitive tool list instead.
    classification = classify_action(tool_name, args, text_scan=tool_is_control)

    if tool_is_control:
        if not info["can_control"]:
            return {
                "decision": "block",
                "level": level,
                "reason": (
                    f"No nível {info['label']} eu não controlo o computador. "
                    "Vou te orientar passo a passo. Mude para 'Assistido' se quiser que eu faça."
                ),
                "sensitive": classification.sensitive,
                "classification": classification.to_dict(),
            }
        if info.get("always_confirm") or classification.sensitive:
            return {"decision": "confirm", "level": level,
                    "reason": ("Ação sensível: preciso da sua confirmação."
                               if classification.sensitive else "Nível assistido: confirme esta ação."),
                    "sensitive": classification.sensitive,
                    "classification": classification.to_dict()}
        return {"decision": "auto", "level": level, "sensitive": False,
                "classification": classification.to_dict()}

    # Non-control tools keep the existing confirmation semantics, but a
    # sensitive classification always forces confirmation even in autonomous mode.
    if classification.sensitive:
        return {"decision": "confirm", "level": level,
                "reason": "Ação sensível: nunca executo sem confirmação.",
                "sensitive": True, "classification": classification.to_dict()}
    if tool_requires_confirmation and legacy_autonomy != "autonomous":
        return {"decision": "confirm", "level": level, "sensitive": False,
                "reason": "Esta ferramenta exige a sua confirmação.",
                "classification": classification.to_dict()}
    return {"decision": "auto", "level": level, "sensitive": False,
            "classification": classification.to_dict()}


# --------------------------------------------------------------------------
# profile guidance
# --------------------------------------------------------------------------
def profile_guidance(profile: str, accessibility: dict[str, Any] | None = None) -> str:
    p = PROFILES.get(profile) or PROFILES[DEFAULT_PROFILE]
    a = accessibility or {}
    lines = [
        "PERFIL DO USUÁRIO",
        f"- Perfil: {p['label']} — {p['description']}",
    ]
    if p["language_level"] == "simple":
        lines += [
            "- Fale de forma muito simples. Frases curtas. Uma ideia por frase.",
            "- Evite termos técnicos. Se precisar usar um, explique em seguida.",
            "- Explique passo a passo, numerando: 'Passo 1', 'Passo 2'…",
            "- Nunca trate a pessoa como incapaz. Nunca demonstre impaciência.",
            "- Se a pessoa disser que não achou algo, acalme e repita com calma.",
        ]
    elif p["language_level"] == "technical":
        lines.append("- Respostas diretas e técnicas; pule o básico.")
    if p["explain_steps"]:
        lines.append("- Antes de agir, diga em uma frase o que vai fazer; depois confirme o resultado.")
    if p["confirm_important"]:
        lines.append("- Peça confirmação clara antes de qualquer ação importante.")
    if a.get("large_text") or a.get("high_contrast") or a.get("big_buttons"):
        enabled = ", ".join(k for k in ("large_text", "high_contrast", "big_buttons", "read_aloud", "calm_voice")
                            if a.get(k))
        lines.append(f"- Recursos de acessibilidade ativos: {enabled}. Considere-os ao responder.")
    return "\n".join(lines)


def autonomy_guidance(level: str) -> str:
    info = AUTONOMY_LEVELS.get(level) or AUTONOMY_LEVELS[DEFAULT_AUTONOMY_LEVEL]
    return (
        "NÍVEL DE AUTONOMIA\n"
        f"- Nível {info['level']}: {info['label']} — {info['description']}\n"
        "- Nunca execute pagamentos, compras, exclusões, mudanças de senha, envio de "
        "documentos/mensagens, ações bancárias ou instalação de programas sem confirmação explícita."
    )


# --------------------------------------------------------------------------
# task controller: cancellation / pause (Part 15)
# --------------------------------------------------------------------------
@dataclass
class TaskRecord:
    conversation_id: str
    state: str = "understanding"
    detail: str = ""
    step: int = 0
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancelled: bool = False
    paused: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id, "state": self.state,
            "label": TASK_STATE_LABELS.get(self.state, self.state.upper()),
            "detail": self.detail, "step": self.step,
            "started_at": self.started_at, "updated_at": self.updated_at,
            "cancelled": self.cancelled, "paused": self.paused, "error": self.error,
        }


class TaskController:
    """Tracks the live state of each conversation's task and handles
    cancel/pause requests coming from the UI or voice commands."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()
        self._pause_events: dict[str, threading.Event] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    def begin(self, conversation_id: str) -> TaskRecord:
        with self._lock:
            rec = TaskRecord(conversation_id, state="understanding")
            self._tasks[conversation_id] = rec
            self._pause_events[conversation_id] = threading.Event()
            self._cancel_events[conversation_id] = threading.Event()
            return rec

    def set_state(self, conversation_id: str, state: str, detail: str = "",
                  step: int | None = None, error: str = "") -> TaskRecord | None:
        with self._lock:
            rec = self._tasks.get(conversation_id)
            if rec is None:
                return None
            rec.state = state
            rec.detail = detail
            rec.updated_at = time.time()
            if step is not None:
                rec.step = step
            if error:
                rec.error = error
            return rec

    def get(self, conversation_id: str) -> TaskRecord | None:
        return self._tasks.get(conversation_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in
                    sorted(self._tasks.values(), key=lambda x: x.updated_at, reverse=True)]

    def request_cancel(self, conversation_id: str) -> bool:
        with self._lock:
            rec = self._tasks.get(conversation_id)
            ev = self._cancel_events.get(conversation_id)
            if ev is None:
                return False
            ev.set()
            if rec:
                rec.cancelled = True
            return True

    def request_pause(self, conversation_id: str, paused: bool = True) -> bool:
        with self._lock:
            ev = self._pause_events.get(conversation_id)
            rec = self._tasks.get(conversation_id)
            if ev is None:
                return False
            if paused:
                ev.set()
            else:
                ev.clear()
            if rec:
                rec.paused = paused
            return True

    def is_cancelled(self, conversation_id: str) -> bool:
        ev = self._cancel_events.get(conversation_id)
        return bool(ev and ev.is_set())

    def wait_if_paused(self, conversation_id: str, timeout: float = 300.0) -> bool:
        """Block while paused. Returns False if the task was cancelled."""
        ev = self._pause_events.get(conversation_id)
        if ev is None:
            return True
        # Wait in small slices so cancellation is honoured promptly.
        waited = 0.0
        while ev.is_set():
            if self.is_cancelled(conversation_id):
                return False
            time.sleep(0.1)
            waited += 0.1
            if waited >= timeout:
                break
        return not self.is_cancelled(conversation_id)

    def finish(self, conversation_id: str, state: str = "done",
               detail: str = "", error: str = "") -> TaskRecord | None:
        rec = self.set_state(conversation_id, state, detail, error=error)
        with self._lock:
            self._pause_events.pop(conversation_id, None)
        return rec

    def clear(self, conversation_id: str) -> None:
        with self._lock:
            self._tasks.pop(conversation_id, None)
            self._pause_events.pop(conversation_id, None)
            self._cancel_events.pop(conversation_id, None)


# Voice cancellation phrases (Part 15).
CANCEL_PHRASES = ("pare", "para", "cancela", "cancelar", "para agora", "pare agora",
                  "cancelar tudo", "chega", "stop")
PAUSE_PHRASES = ("pausa", "pausar", "espera", "aguarde", "pause")
RESUME_PHRASES = ("continue", "continuar", "retome", "retomar", "prossiga", "volte")


def detect_control_phrase(text: str) -> str | None:
    """Return 'cancel' | 'pause' | 'resume' | None for a short spoken/typed command."""
    if not text:
        return None
    low = text.strip().lower().rstrip(".!?")
    words = low.split()
    if len(words) > 4:
        return None
    if any(low == p or low.startswith(p + " ") for p in CANCEL_PHRASES):
        return "cancel"
    if any(low == p or low.startswith(p + " ") for p in PAUSE_PHRASES):
        return "pause"
    if any(low == p or low.startswith(p + " ") for p in RESUME_PHRASES):
        return "resume"
    return None


# Global controller instance.
controller = TaskController()
# Convenience alias used by the agent loop and the REST API.
task_controller = controller


def new_id() -> str:
    return uuid.uuid4().hex
