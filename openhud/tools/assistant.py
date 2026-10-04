"""Computer-assistant tools: screen vision, element finding and input control.

These tools talk to the OpenHUD Agent running on the user's PC through the
Agent Hub. They never touch the machine directly from the server.

Safety model:
  * every tool is marked ``requires_confirmation`` for control actions; the
    agent loop additionally applies the autonomy-level gate and the
    sensitive-action policy (see :mod:`openhud.core.assist`).
  * ``control`` tools are tagged so the loop can block them in observe/guide
    levels even before the model asks.
  * when no PC is connected, or a permission/backend is missing, the tool
    returns the real error — it never pretends the action happened.
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolResult

# Tools that physically control the machine; used by the autonomy gate.
CONTROL_TOOLS = {
    "pc_mouse_move", "pc_mouse_click", "pc_mouse_double_click", "pc_mouse_scroll",
    "pc_keyboard_type", "pc_keyboard_press", "pc_open_application", "pc_open_url",
    "pc_window_focus", "pc_window_close",
}


def _target_device(args: dict[str, Any]) -> tuple[str | None, str | None]:
    """Resolve which device to talk to (explicit id, or the first online PC)."""
    from ..core.agent_hub import get_hub

    try:
        hub = get_hub()
    except RuntimeError as exc:
        return None, str(exc)
    device_id = args.get("device_id")
    if device_id:
        return device_id, None
    devices = [d for d in hub.list_devices() if d["id"] != "local"]
    online = [d for d in devices if d["online"]]
    chosen = online or devices
    if not chosen:
        return None, "Nenhum computador conectado. Abra o OpenHUD Agent no PC e faça o pareamento."
    return chosen[0]["id"], None


def _call(command: str, args: dict[str, Any], timeout: float = 30.0) -> ToolResult:
    from ..core.agent_hub import get_hub

    device_id, err = _target_device(args)
    if err:
        return ToolResult(False, err)
    hub = get_hub()
    try:
        res = hub.request(device_id, command, args, timeout=timeout)
    except KeyError:
        return ToolResult(False, "Dispositivo não encontrado.")
    except PermissionError as exc:
        return ToolResult(False, f"Permissão negada: {exc}")
    except (TimeoutError, RuntimeError) as exc:
        return ToolResult(False, str(exc))
    if not res.get("ok", False):
        return ToolResult(False, res.get("error", "O PC não conseguiu executar a ação."), res)
    return ToolResult(True, _format(command, res), res)


def _format(command: str, res: dict[str, Any]) -> str:
    if command == "screen_analyze":
        counts = res.get("counts") or {}
        lines = [f"Tela {res.get('width')}x{res.get('height')}.",
                 res.get("summary", "")]
        if counts:
            lines.append("Contagem: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        for e in (res.get("errors") or [])[:5]:
            lines.append(f"⚠ {e['text']}")
        return "\n".join(l for l in lines if l)
    if command in ("screen_find", "screen_highlight"):
        matches = res.get("matches") or ([res["highlight"]] if res.get("highlight") else [])
        if not matches:
            return res.get("note", "Nenhum elemento correspondente encontrado na tela.")
        lines = []
        for m in matches[:5]:
            b = m["box"]
            lines.append(f"{m['kind']} '{m['text']}' em ({b['cx']}, {b['cy']})")
        return "\n".join(lines)
    if command == "screen_capture":
        return f"Captura salva em {res.get('path')} ({res.get('width')}x{res.get('height')})."
    if command == "window_list":
        wins = res.get("windows") or []
        return "Janelas abertas:\n" + "\n".join(f"- {w['title']}" for w in wins[:30])
    if command == "mouse_move":
        return f"Mouse movido para ({res.get('x')}, {res.get('y')})."
    if command in ("mouse_click", "mouse_double_click"):
        return f"Clique ({res.get('clicks', 1)}x) em ({res.get('x')}, {res.get('y')})."
    if command == "mouse_scroll":
        return f"Rolagem de {res.get('amount')}."
    if command == "keyboard_type":
        return f"Digitado ({res.get('chars')} caracteres)."
    if command == "keyboard_press":
        return f"Tecla(s) pressionada(s): {res.get('keys')}."
    if command == "open_url":
        return f"Navegador aberto em {res.get('url')}."
    if command == "open_application":
        return f"Aplicativo/arquivo aberto: {res.get('target')}."
    if command == "window_focus":
        return f"Janela em foco: {res.get('title')}."
    if command == "window_close":
        return f"Janela fechada: {res.get('title')}."
    return "Ação concluída."


class PcScreenCaptureTool(Tool):
    name = "pc_screen_capture"
    description = (
        "Captura a tela atual do PC conectado e salva uma imagem. Use quando o usuário "
        "perguntar 'o que apareceu na tela?'. Requer a permissão 'screen'. Se não houver "
        "backend de captura no PC, retorna o erro real."
    )
    parameters = {"type": "object", "properties": {"device_id": {"type": "string"}}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("screen_capture", args)


class PcScreenAnalyzeTool(Tool):
    name = "pc_screen_analyze"
    description = (
        "Lê a tela do PC conectado (captura + OCR) e descreve botões, campos, menus, links "
        "e mensagens de erro. Não inventa elementos: se não conseguir ler a tela, informa. "
        "Requer a permissão 'screen'."
    )
    parameters = {"type": "object", "properties": {"device_id": {"type": "string"}}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("screen_analyze", args, timeout=45.0)


class PcFindElementTool(Tool):
    name = "pc_find_element"
    description = (
        "Procura um elemento (botão, campo, link) na tela atual do PC por descrição "
        "em linguagem natural, ex.: 'botão Entrar'. Retorna a posição para guiar o usuário."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Descrição do elemento, ex.: 'botão Entrar'."},
            "device_id": {"type": "string"},
        },
        "required": ["query"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("screen_find", args, timeout=45.0)


class PcHighlightElementTool(Tool):
    name = "pc_highlight_element"
    description = (
        "Localiza um elemento na tela e devolve sua caixa (posição) para que a interface "
        "destaque visualmente onde o usuário deve clicar."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Descrição do elemento."},
            "device_id": {"type": "string"},
        },
        "required": ["query"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("screen_highlight", args, timeout=45.0)


class PcWindowListTool(Tool):
    name = "pc_window_list"
    description = "Lista as janelas abertas no PC conectado (títulos). Requer a permissão 'screen'."
    parameters = {"type": "object", "properties": {"device_id": {"type": "string"}}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("window_list", args)


# --------------------------------------------------------------------------
# input control
# --------------------------------------------------------------------------
class PcMouseMoveTool(Tool):
    name = "pc_mouse_move"
    description = "Move o cursor do mouse do PC conectado para as coordenadas (x, y). Requer a permissão 'control'."
    parameters = {
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                       "device_id": {"type": "string"}},
        "required": ["x", "y"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("mouse_move", args)


class PcMouseClickTool(Tool):
    name = "pc_mouse_click"
    description = "Clica com o mouse no PC conectado, opcionalmente nas coordenadas (x, y). Requer a permissão 'control'."
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "device_id": {"type": "string"},
        },
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("mouse_click", args)


class PcMouseDoubleClickTool(Tool):
    name = "pc_mouse_double_click"
    description = "Dá duplo clique com o mouse no PC conectado, opcionalmente em (x, y). Requer a permissão 'control'."
    parameters = {
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                       "device_id": {"type": "string"}},
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("mouse_double_click", args)


class PcMouseScrollTool(Tool):
    name = "pc_mouse_scroll"
    description = "Rola a página no PC conectado (positivo = para cima). Requer a permissão 'control'."
    parameters = {
        "type": "object",
        "properties": {"amount": {"type": "integer"}, "device_id": {"type": "string"}},
        "required": ["amount"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("mouse_scroll", args)


class PcKeyboardTypeTool(Tool):
    name = "pc_keyboard_type"
    description = "Digita um texto no PC conectado (no campo ativo). Requer a permissão 'control'."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "device_id": {"type": "string"}},
        "required": ["text"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("keyboard_type", args)


class PcKeyboardPressTool(Tool):
    name = "pc_keyboard_press"
    description = (
        "Pressiona teclas no PC conectado, ex.: 'enter', 'ctrl s', 'alt tab'. "
        "Requer a permissão 'control'."
    )
    parameters = {
        "type": "object",
        "properties": {"keys": {"type": "string"}, "device_id": {"type": "string"}},
        "required": ["keys"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("keyboard_press", args)


class PcOpenUrlTool(Tool):
    name = "pc_open_url"
    description = "Abre uma URL no navegador padrão do PC conectado. Requer a permissão 'control'."
    parameters = {
        "type": "object",
        "properties": {"url": {"type": "string"}, "device_id": {"type": "string"}},
        "required": ["url"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("open_url", args)


class PcOpenApplicationTool(Tool):
    name = "pc_open_application"
    description = (
        "Abre um aplicativo ou documento no PC conectado (ex.: 'notepad', 'C:/Doc.pdf'). "
        "Não instala nada e não baixa arquivos. Requer a permissão 'control'."
    )
    parameters = {
        "type": "object",
        "properties": {"target": {"type": "string"}, "device_id": {"type": "string"}},
        "required": ["target"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("open_application", args)


class PcWindowFocusTool(Tool):
    name = "pc_window_focus"
    description = "Coloca uma janela em foco pelo título, no PC conectado. Requer a permissão 'control'."
    parameters = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "device_id": {"type": "string"}},
        "required": ["title"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("window_focus", args)


class PcWindowCloseTool(Tool):
    name = "pc_window_close"
    description = "Fecha uma janela pelo título, no PC conectado. Requer a permissão 'control'."
    parameters = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "device_id": {"type": "string"}},
        "required": ["title"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return _call("window_close", args)


def build_assistant_tools() -> list[Tool]:
    return [
        PcScreenCaptureTool(), PcScreenAnalyzeTool(), PcFindElementTool(),
        PcHighlightElementTool(), PcWindowListTool(),
        PcMouseMoveTool(), PcMouseClickTool(), PcMouseDoubleClickTool(), PcMouseScrollTool(),
        PcKeyboardTypeTool(), PcKeyboardPressTool(), PcOpenUrlTool(), PcOpenApplicationTool(),
        PcWindowFocusTool(), PcWindowCloseTool(),
    ]
