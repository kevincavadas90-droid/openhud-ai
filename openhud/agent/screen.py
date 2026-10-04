"""Screen capture, OCR-based element detection and input control for the PC
agent (Parts 3 and 4).

This module is imported by the OpenHUD Agent running *on the user's PC*, so
every heavy dependency is optional and imported lazily. When a dependency is
missing the functions return an explicit error — they never fake a capture or
invent an element that is not on screen.

Design:
  * capture uses ``mss`` (fast, cross-platform) or falls back to ``Pillow``.
  * OCR uses ``pytesseract`` + the Tesseract binary; without it, analysis
    reports that OCR is unavailable rather than guessing.
  * element detection is pure: it turns OCR word boxes into candidate buttons,
    fields, links and text, using geometry and keywords. It is unit-testable
    with a synthetic box list and does not require a real screen.
  * input control uses ``pyautogui``; every mutating action is gated by the
    caller (the server checks the autonomy level and permissions first).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# optional dependencies
# --------------------------------------------------------------------------
def _has(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def capabilities() -> dict[str, Any]:
    return {
        "capture": _has("mss") or _has("PIL"),
        "ocr": _has("pytesseract") and _binary("tesseract"),
        "control": _has("pyautogui"),
        "windows": _has("pygetwindow") or _has("pywinauto"),
        "clipboard": _has("pyperclip"),
    }


def _binary(name: str) -> bool:
    import shutil

    return shutil.which(name) is not None


# --------------------------------------------------------------------------
# element detection (pure, testable)
# --------------------------------------------------------------------------
# Keywords that hint at the semantic role of a text element.
_FIELD_HINTS = ("e-mail", "email", "senha", "password", "usuário", "usuario", "user",
                "login", "nome", "name", "buscar", "busca", "search", "pesquisar",
                "telefone", "celular", "cpf", "endereço", "endereco", "mensagem",
                "comentário", "comentario", "pesquisa", "digite", "type", "enter")
_BUTTON_HINTS = ("entrar", "login", "log in", "sign in", "acessar", "enviar", "send",
                 "confirmar", "confirm", "ok", "continuar", "continue", "próximo",
                 "proximo", "next", "salvar", "save", "aceitar", "accept", "criar",
                 "cadastrar", "registrar", "comprar", "buy", "pagar", "pay", "baixar",
                 "download", "abrir", "open", "fechar", "close", "cancelar", "cancel",
                 "voltar", "back", "menu", "iniciar", "start", "pesquisar", "search")
_LINK_HINTS = ("www.", "http", ".com", ".com.br", ".br", "clique aqui", "click here")
_ERROR_HINTS = ("erro", "error", "falha", "failed", "inválido", "invalido", "incorreto",
                "não foi possível", "nao foi possivel", "negado", "denied", "atenção",
                "atencao", "warning", "aviso")


@dataclass
class Box:
    """A word/line detected on screen with its bounding box (pixels)."""

    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "x": self.x, "y": self.y, "w": self.w, "h": self.h,
                "cx": self.cx, "cy": self.cy}


@dataclass
class Element:
    kind: str  # button | field | link | text | error | menu | icon
    text: str
    box: Box
    role: str = ""
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "role": self.role,
                "confidence": round(self.confidence, 2), "box": self.box.to_dict()}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _kind_for(text: str) -> tuple[str, str, float]:
    low = _norm(text)
    if any(h in low for h in _ERROR_HINTS):
        return "error", "mensagem de erro", 0.7
    if any(h in low for h in _LINK_HINTS):
        return "link", "link", 0.6
    if low in _BUTTON_HINTS or any(low == h or low.startswith(h + " ") or low.endswith(" " + h)
                                   for h in _BUTTON_HINTS):
        return "button", "botão", 0.75
    if any(h in low for h in _FIELD_HINTS):
        return "field", "campo", 0.6
    return "text", "texto", 0.4


def detect_elements(boxes: list[dict[str, Any]], screen_w: int = 0, screen_h: int = 0) -> list[Element]:
    """Turn OCR boxes into candidate UI elements. Pure function."""
    elements: list[Element] = []
    for raw in boxes or []:
        try:
            box = Box(str(raw.get("text", "")), int(raw.get("x", 0)), int(raw.get("y", 0)),
                      int(raw.get("w", 0)), int(raw.get("h", 0)))
        except (TypeError, ValueError):
            continue
        if not box.text.strip():
            continue
        kind, role, conf = _kind_for(box.text)
        # A short, isolated, wide-enough box near an edge is likely a menu/tab.
        if kind == "text" and len(box.text) <= 18 and box.w >= 40 and screen_w:
            if box.x < screen_w * 0.15 or box.y < screen_h * 0.12:
                kind, role, conf = "menu", "menu/aba", 0.45
        elements.append(Element(kind, box.text, box, role, conf))
    return elements


def elements_from_dicts(items: list[dict[str, Any]]) -> list[Element]:
    """Rebuild Element objects from the serialised dicts returned by the
    analysis pipeline (used by the find/highlight commands)."""
    out: list[Element] = []
    for e in items or []:
        box = e.get("box") or {}
        out.append(Element(
            e.get("kind", "text"), e.get("text", ""),
            Box(str(e.get("text", "")), int(box.get("x", 0)), int(box.get("y", 0)),
                int(box.get("w", 0)), int(box.get("h", 0))),
            e.get("role", ""), float(e.get("confidence", 0.5)),
        ))
    return out


def find_matches(elements: list[Element], query: str) -> list[Element]:
    """Rank elements by how well they match a natural-language query."""
    q = _norm(query)
    if not q:
        return []
    terms = [t for t in re.split(r"\s+", q) if len(t) > 2]
    scored: list[tuple[float, Element]] = []
    for el in elements:
        text = _norm(el.text)
        score = 0.0
        if q in text or text in q:
            score += 1.0
        for t in terms:
            if t in text:
                score += 0.4
        if el.kind == "button" and any(t in text for t in terms):
            score += 0.2
        if score > 0:
            scored.append((score, el))
    scored.sort(key=lambda kv: kv[0], reverse=True)
    return [el for _, el in scored]


def summarize_screen(elements: list[Element], width: int = 0, height: int = 0) -> dict[str, Any]:
    """A compact, human-readable description of what is on screen."""
    by_kind: dict[str, list[Element]] = {}
    for el in elements:
        by_kind.setdefault(el.kind, []).append(el)
    errors = by_kind.get("error", [])
    lines: list[str] = []
    for kind, label in (("button", "botões"), ("field", "campos"), ("link", "links"),
                        ("menu", "menus/abas"), ("error", "avisos/erros")):
        items = by_kind.get(kind, [])
        if items:
            sample = ", ".join(e.text for e in items[:8])
            lines.append(f"{label.capitalize()}: {sample}")
    return {
        "width": width, "height": height,
        "counts": {k: len(v) for k, v in by_kind.items()},
        "elements": [e.to_dict() for e in elements],
        "errors": [e.to_dict() for e in errors],
        "summary": " · ".join(lines) if lines else "Nenhum elemento de interface reconhecido.",
        "readable": bool(elements),
    }


# --------------------------------------------------------------------------
# capture (agent-side; optional deps)
# --------------------------------------------------------------------------
def capture_screen(path: Path | None = None) -> dict[str, Any]:
    """Capture the primary screen to a PNG file. Returns an honest error when
    no capture backend is available."""
    caps = capabilities()
    if not caps["capture"]:
        return {"ok": False, "error": "Captura de tela indisponível: instale 'mss' ou 'Pillow' no PC."}
    try:
        import time

        out = path or Path("screen.png")
        if _has("mss"):
            import mss  # type: ignore

            with mss.mss() as sct:
                monitor = sct.monitors[0]
                shot = sct.grab(monitor)
                try:
                    from PIL import Image  # type: ignore

                    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                    img.save(out)
                except Exception:
                    import mss.tools  # type: ignore

                    mss.tools.to_png(shot.rgb, shot.size, output=str(out))
                size = (monitor["width"], monitor["height"])
        else:  # Pillow ImageGrab (Windows/macOS)
            from PIL import ImageGrab  # type: ignore

            img = ImageGrab.grab()
            img.save(out)
            size = img.size
        return {"ok": True, "path": str(out), "width": size[0], "height": size[1],
                "captured_at": time.time()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def ocr_boxes(path: Path) -> dict[str, Any]:
    """Run OCR and return word boxes. Honest error without Tesseract."""
    if not capabilities()["ocr"]:
        return {"ok": False, "error": "OCR indisponível: instale 'pytesseract' e o Tesseract no PC."}
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        data = pytesseract.image_to_data(Image.open(path), output_type=pytesseract.Output.DICT)
        boxes = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1
            if conf < 30:
                continue
            boxes.append({"text": text, "x": int(data["left"][i]), "y": int(data["top"][i]),
                          "w": int(data["width"][i]), "h": int(data["height"][i])})
        return {"ok": True, "boxes": boxes}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def analyze_screen() -> dict[str, Any]:
    """Capture + OCR + detect. The full pipeline used by pc_screen_analyze."""
    import tempfile

    tmp = Path(tempfile.gettempdir()) / "openhud-screen.png"
    cap = capture_screen(tmp)
    if not cap.get("ok"):
        return cap
    ocr = ocr_boxes(tmp)
    if not ocr.get("ok"):
        # We captured the screen but cannot read it — say so explicitly.
        return {"ok": False, "error": ocr.get("error"), "captured": True,
                "width": cap["width"], "height": cap["height"], "path": cap["path"]}
    elements = detect_elements(ocr["boxes"], cap["width"], cap["height"])
    summary = summarize_screen(elements, cap["width"], cap["height"])
    return {"ok": True, "path": cap["path"], "width": cap["width"], "height": cap["height"],
            **summary}


# --------------------------------------------------------------------------
# input control (agent-side; gated by the server)
# --------------------------------------------------------------------------
def _gui():
    import pyautogui  # type: ignore

    pyautogui.FAILSAFE = True  # moving to a corner aborts
    return pyautogui


def control_capabilities() -> dict[str, Any]:
    return {"available": _has("pyautogui"), "note": "Controle de mouse/teclado via pyautogui."}


def mouse_move(x: int, y: int, duration: float = 0.2) -> dict[str, Any]:
    if not _has("pyautogui"):
        return {"ok": False, "error": "Controle indisponível: instale 'pyautogui' no PC."}
    try:
        _gui().moveTo(int(x), int(y), duration=duration)
        return {"ok": True, "x": int(x), "y": int(y)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def mouse_click(x: int | None = None, y: int | None = None, button: str = "left",
                clicks: int = 1) -> dict[str, Any]:
    if not _has("pyautogui"):
        return {"ok": False, "error": "Controle indisponível: instale 'pyautogui' no PC."}
    try:
        g = _gui()
        if x is not None and y is not None:
            g.moveTo(int(x), int(y), duration=0.15)
        g.click(button=button, clicks=max(1, min(int(clicks), 3)))
        return {"ok": True, "x": x, "y": y, "button": button, "clicks": clicks}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def mouse_scroll(amount: int) -> dict[str, Any]:
    if not _has("pyautogui"):
        return {"ok": False, "error": "Controle indisponível: instale 'pyautogui' no PC."}
    try:
        _gui().scroll(int(amount))
        return {"ok": True, "amount": int(amount)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def keyboard_type(text: str, interval: float = 0.02) -> dict[str, Any]:
    if not _has("pyautogui"):
        return {"ok": False, "error": "Controle indisponível: instale 'pyautogui' no PC."}
    try:
        _gui().typewrite(text, interval=interval)
        return {"ok": True, "chars": len(text)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def keyboard_press(keys: str) -> dict[str, Any]:
    if not _has("pyautogui"):
        return {"ok": False, "error": "Controle indisponível: instale 'pyautogui' no PC."}
    try:
        g = _gui()
        parts = [k.strip() for k in keys.replace("+", " ").split() if k.strip()]
        if len(parts) > 1:
            g.hotkey(*parts)
        elif parts:
            g.press(parts[0])
        return {"ok": True, "keys": keys}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def open_url(url: str) -> dict[str, Any]:
    """Open a URL in the default browser."""
    import webbrowser

    try:
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        opened = webbrowser.open(url)
        if not opened:
            return {"ok": False, "error": "Não foi possível abrir o navegador."}
        return {"ok": True, "url": url}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def open_application(target: str) -> dict[str, Any]:
    """Open an application or document using the OS handler.

    Only opens what the user named; never downloads or installs anything.
    """
    import os
    import platform
    import subprocess

    try:
        if platform.system() == "Windows":
            os.startfile(target)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return {"ok": True, "target": target}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def window_list() -> dict[str, Any]:
    if not (_has("pygetwindow") or _has("pywinauto")):
        return {"ok": False, "error": "Listagem de janelas indisponível: instale 'pygetwindow' no PC."}
    try:
        import pygetwindow as gw  # type: ignore

        wins = [{"title": w.title, "left": w.left, "top": w.top, "width": w.width, "height": w.height}
                for w in gw.getAllWindows() if (w.title or "").strip()]
        return {"ok": True, "windows": wins}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def window_focus(title: str) -> dict[str, Any]:
    if not (_has("pygetwindow") or _has("pywinauto")):
        return {"ok": False, "error": "Foco de janela indisponível: instale 'pygetwindow' no PC."}
    try:
        import pygetwindow as gw  # type: ignore

        matches = gw.getWindowsWithTitle(title)
        if not matches:
            return {"ok": False, "error": f"Nenhuma janela encontrada com o título '{title}'."}
        matches[0].activate()
        return {"ok": True, "title": matches[0].title}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def window_close(title: str) -> dict[str, Any]:
    if not (_has("pygetwindow") or _has("pywinauto")):
        return {"ok": False, "error": "Controle de janela indisponível: instale 'pygetwindow' no PC."}
    try:
        import pygetwindow as gw  # type: ignore

        matches = gw.getWindowsWithTitle(title)
        if not matches:
            return {"ok": False, "error": f"Nenhuma janela encontrada com o título '{title}'."}
        matches[0].close()
        return {"ok": True, "title": matches[0].title}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
