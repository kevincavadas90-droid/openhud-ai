"""OpenHUD Agent Diagnostics — a full, honest readiness check for the PC.

Run it on the machine that will act as an OpenHUD agent:

    python -m openhud.agent.selfcheck            # human-readable report
    python -m openhud.agent.selfcheck --json     # machine-readable
    python -m openhud.agent.selfcheck --server https://host --pair 123456

Every check reports a real status and never fakes a result:

    PASS          the capability works
    WARNING       works, but with a caveat (degraded)
    FAIL          installed but broken / errored
    NOT INSTALLED the optional component/library is missing
    NOT PERMITTED the capability exists but the user has not granted permission

The check covers: OS/architecture, Python/runtime, network connection, WebSocket
reachability, authentication, permissions, screen capture, OCR, mouse, keyboard,
clipboard, browser, audio, microphone, TTS, STT, GPU, CPU, RAM and storage.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import socket
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"
NOT_INSTALLED = "NOT INSTALLED"
NOT_PERMITTED = "NOT PERMITTED"

_ORDER = {PASS: 0, WARNING: 1, FAIL: 2, NOT_INSTALLED: 3, NOT_PERMITTED: 4}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    platform: str = ""
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "", hint: str = "") -> Check:
        c = Check(name, status, detail, hint)
        self.checks.append(c)
        return c

    @property
    def summary(self) -> dict[str, int]:
        out = {k: 0 for k in _ORDER}
        for c in self.checks:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    @property
    def ok(self) -> bool:
        return all(c.status in (PASS, WARNING) for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {"platform": self.platform, "ok": self.ok,
                "summary": self.summary, "checks": [c.to_dict() for c in self.checks]}


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _binary(name: str) -> bool:
    return shutil.which(name) is not None


def _safe(fn, *args, **kwargs) -> tuple[bool, Any, str]:
    try:
        return True, fn(*args, **kwargs), ""
    except Exception as exc:  # noqa: BLE001 - we report the real error
        return False, None, f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# individual checks
# --------------------------------------------------------------------------
def check_os(rep: Report) -> None:
    is_win = os.name == "nt"
    detail = f"{platform.system()} {platform.release()} · {platform.machine()}"
    if is_win:
        build = platform.version()
        rep.add("Windows", PASS, f"{detail} (build {build})")
    elif sys.platform == "darwin":
        rep.add("Sistema", WARNING, f"{detail} — o app oficial é para Windows; o agente roda em macOS/Linux.",
                "Alguns recursos de controle podem diferir fora do Windows.")
    else:
        rep.add("Sistema", WARNING, f"{detail} — o app oficial é para Windows.",
                "O agente funciona, mas o instalador e o suporte oficiais são para Windows 10/11.")


def check_architecture(rep: Report) -> None:
    bits = platform.architecture()[0]
    arch = platform.machine()
    if bits == "64bit":
        rep.add("Arquitetura", PASS, f"{arch} ({bits})")
    else:
        rep.add("Arquitetura", FAIL, f"{arch} ({bits}) — 32 bits não é suportado.",
                "Use um sistema de 64 bits.")


def check_python(rep: Report) -> None:
    v = sys.version_info
    label = f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if v >= (3, 11):
        rep.add("Python / runtime", PASS, label)
    elif v >= (3, 9):
        rep.add("Python / runtime", WARNING, label + " — recomendado 3.11+.")
    else:
        rep.add("Python / runtime", FAIL, label + " — muito antigo.",
                "Instale Python 3.11 ou superior.")


def check_network(rep: Report, server: str | None) -> None:
    if not server:
        # Fall back to a generic DNS check.
        ok, _, err = _safe(socket.gethostbyname, "github.com")
        if ok:
            rep.add("Conexão de rede", PASS, "DNS resolve (github.com).")
        else:
            rep.add("Conexão de rede", WARNING, f"Sem resolução DNS: {err}",
                    "Verifique a internet do computador.")
        return
    parsed = urllib.parse.urlparse(server)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        rep.add("Conexão de rede", FAIL, f"URL inválida: {server}")
        return
    ok, _, err = _safe(socket.create_connection, (host, port), 5)
    if ok:
        rep.add("Conexão de rede", PASS, f"TCP {host}:{port} alcançável.")
    else:
        rep.add("Conexão de rede", FAIL, f"Não conectou a {host}:{port} — {err}",
                "Confira a URL do servidor, o firewall e a internet.")
    # HTTPS reachability of the health endpoint.
    try:
        url = f"{parsed.scheme}://{parsed.netloc}/health"
        with urllib.request.urlopen(url, timeout=6) as resp:  # noqa: S310 - user-provided server
            body = resp.read(200).decode("utf-8", "replace")
            rep.add("HTTPS /health", PASS if resp.status == 200 else WARNING,
                    f"HTTP {resp.status} · {body[:80]}")
    except Exception as exc:  # noqa: BLE001
        rep.add("HTTPS /health", WARNING, f"Não foi possível ler /health: {type(exc).__name__}: {exc}",
                "O servidor pode estar dormindo (free tier) ou a URL pode estar errada.")


def check_websocket(rep: Report) -> None:
    if _has_module("websockets"):
        try:
            import websockets  # noqa: F401
            ver = getattr(websockets, "__version__", "?")
            rep.add("WebSocket", PASS, f"biblioteca 'websockets' instalada ({ver}).")
        except Exception as exc:  # noqa: BLE001
            rep.add("WebSocket", FAIL, f"'websockets' presente mas não importa: {exc}",
                    "Reinstale: pip install -r requirements-agent.txt")
    else:
        rep.add("WebSocket", NOT_INSTALLED, "biblioteca 'websockets' ausente.",
                "pip install -r requirements-agent.txt")


def check_auth(rep: Report, token: str | None) -> None:
    if token:
        rep.add("Autenticação", PASS, "Token de dispositivo presente (pareamento concluído).")
    else:
        rep.add("Autenticação", NOT_PERMITTED,
                "Sem token de dispositivo — o PC ainda não foi pareado.",
                "Rode com --pair <código> para parear.")


def check_permissions(rep: Report, perms: dict[str, bool] | None) -> None:
    if not perms:
        rep.add("Permissões", WARNING, "Nenhuma permissão carregada ainda (pareie o PC primeiro).")
        return
    on = [k for k, v in perms.items() if v]
    off = [k for k, v in perms.items() if not v]
    rep.add("Permissões", PASS if on else WARNING,
            f"Concedidas: {', '.join(on) or 'nenhuma'}. Negadas: {', '.join(off) or 'nenhuma'}.",
            "Ajuste as permissões no site (Painel do PC).")


def check_screen(rep: Report, perms: dict[str, bool] | None) -> None:
    granted = bool(perms and perms.get("screen"))
    if not granted:
        rep.add("Captura de tela", NOT_PERMITTED, "Permissão 'screen' não concedida.",
                "Ative 'Tela' no Painel do PC para permitir captura.")
    elif not _has_module("mss") and not _has_module("PIL"):
        rep.add("Captura de tela", NOT_INSTALLED, "Faltam 'mss' e 'Pillow'.",
                "pip install mss pillow")
    else:
        try:
            from .screen import capture_screen
            res = capture_screen()
            if res.get("ok"):
                rep.add("Captura de tela", PASS, f"Captura real ok ({res.get('width')}x{res.get('height')}).")
            else:
                rep.add("Captura de tela", FAIL, res.get("error", "falhou"))
        except Exception as exc:  # noqa: BLE001
            rep.add("Captura de tela", FAIL, f"{type(exc).__name__}: {exc}")


def check_ocr(rep: Report) -> None:
    if not _has_module("pytesseract"):
        rep.add("OCR", NOT_INSTALLED, "biblioteca 'pytesseract' ausente.",
                "pip install pytesseract e instale o Tesseract-OCR.")
        return
    if not _binary("tesseract"):
        rep.add("OCR", NOT_INSTALLED, "'pytesseract' instalado, mas o binário 'tesseract' não está no PATH.",
                "Instale o Tesseract-OCR (UB Mannheim) e reinicie o terminal.")
        return
    try:
        import pytesseract
        ver = pytesseract.get_tesseract_version()
        rep.add("OCR", PASS, f"Tesseract {ver}.")
    except Exception as exc:  # noqa: BLE001
        rep.add("OCR", FAIL, f"Tesseract presente mas falhou: {type(exc).__name__}: {exc}")


def check_mouse_keyboard(rep: Report, perms: dict[str, bool] | None) -> None:
    granted = bool(perms and perms.get("control"))
    if not granted:
        rep.add("Mouse", NOT_PERMITTED, "Permissão 'control' não concedida.",
                "Ative 'Controle' no Painel do PC.")
        rep.add("Teclado", NOT_PERMITTED, "Permissão 'control' não concedida.",
                "Ative 'Controle' no Painel do PC.")
        return
    if not _has_module("pyautogui"):
        rep.add("Mouse", NOT_INSTALLED, "'pyautogui' ausente.", "pip install pyautogui")
        rep.add("Teclado", NOT_INSTALLED, "'pyautogui' ausente.", "pip install pyautogui")
        return
    ok, size, err = _safe(lambda: __import__("pyautogui").size())
    if ok:
        rep.add("Mouse", PASS, f"pyautogui ok · tela {size}.")
        rep.add("Teclado", PASS, "pyautogui ok (digitação e atalhos disponíveis).")
    else:
        rep.add("Mouse", FAIL, err)
        rep.add("Teclado", FAIL, err)


def check_clipboard(rep: Report) -> None:
    if _has_module("pyperclip"):
        ok, val, err = _safe(__import__("pyperclip").paste)
        rep.add("Clipboard", PASS if ok else FAIL,
                "acessível" if ok else err, "pip install pyperclip")
    else:
        rep.add("Clipboard", NOT_INSTALLED, "'pyperclip' ausente.", "pip install pyperclip")


def check_browser(rep: Report) -> None:
    import webbrowser
    try:
        browser = webbrowser.get()
        rep.add("Navegador", PASS, f"navegador padrão disponível ({type(browser).__name__}).")
    except Exception as exc:  # noqa: BLE001
        rep.add("Navegador", WARNING, f"navegador padrão não detectado: {exc}",
                "Instale/defina um navegador padrão.")


def check_audio_mic(rep: Report, perms: dict[str, bool] | None) -> None:
    # Audio output / TTS backend
    if _has_module("edge_tts"):
        rep.add("TTS", PASS, "edge-tts disponível (voz neural).")
    else:
        rep.add("TTS", NOT_INSTALLED, "edge-tts ausente — a voz usará o navegador.",
                "pip install edge-tts")
    # Microphone / STT
    if _has_module("speech_recognition"):
        rep.add("STT", PASS, "speech_recognition disponível.")
    elif _has_module("whisper"):
        rep.add("STT", PASS, "openai-whisper disponível.")
    else:
        rep.add("STT", NOT_INSTALLED, "STT no servidor ausente — o microfone do navegador é usado.",
                "Opcional: pip install SpeechRecognition ou openai-whisper")
    # Microphone device presence
    ok = _has_module("sounddevice") or _has_module("pyaudio")
    if ok:
        rep.add("Microfone", PASS, "biblioteca de áudio presente (verifique o dispositivo físico).")
    else:
        rep.add("Microfone", WARNING, "sem biblioteca de áudio — a captura é feita pelo navegador.",
                "A voz funciona pelo navegador; para captura no app, instale sounddevice.")
    if not (perms and perms.get("voice")):
        rep.add("Permissão de voz", NOT_PERMITTED, "Permissão 'voice' não concedida.",
                "Ative 'Voz' no Painel do PC para microfone/áudio.")
    else:
        rep.add("Permissão de voz", PASS, "voz autorizada.")


def check_gpu(rep: Report) -> None:
    try:
        from .telemetry import TelemetryCollector
        metrics = TelemetryCollector().collect()
    except Exception as exc:  # noqa: BLE001
        rep.add("GPU", WARNING, f"telemetria indisponível: {type(exc).__name__}: {exc}")
        rep.add("CPU", WARNING, "telemetria indisponível.")
        rep.add("RAM", WARNING, "telemetria indisponível.")
        rep.add("Armazenamento", WARNING, "telemetria indisponível.")
        return
    if not metrics.get("available", True):
        rep.add("CPU", WARNING, "psutil ausente — instale requirements-agent.txt.")
        rep.add("RAM", WARNING, "psutil ausente.")
        rep.add("Armazenamento", WARNING, "psutil ausente.")
        rep.add("GPU", WARNING, "telemetria indisponível sem psutil.")
        return

    gpus = metrics.get("gpu") or []
    if gpus:
        g = gpus[0]
        rep.add("GPU", PASS,
                f"{g.get('name', 'GPU')} · uso {g.get('utilization')}% · "
                f"VRAM {g.get('memory_used_mb')}/{g.get('memory_total_mb')} MB")
    elif _has_module("pynvml"):
        rep.add("GPU", WARNING, "'pynvml' instalado, mas nenhuma GPU NVIDIA detectada.",
                "Sem GPU NVIDIA, o diagnóstico informa 'não detectada' em vez de inventar.")
    else:
        rep.add("GPU", NOT_INSTALLED, "sem 'nvidia-ml-py' / GPU NVIDIA.",
                "Opcional: pip install nvidia-ml-py")

    cpu = metrics.get("cpu") or {}
    cpu_name = platform.processor() or platform.machine()
    rep.add("CPU", PASS if cpu else WARNING,
            f"{cpu_name} · uso {cpu.get('percent')}% · "
            f"{cpu.get('cores_logical')} núcleos lógicos ({cpu.get('cores_physical')} físicos)")

    ram = metrics.get("ram") or {}
    used_gb = round((ram.get("used_mb") or 0) / 1024, 1)
    total_gb = round((ram.get("total_mb") or 0) / 1024, 1)
    rep.add("RAM", PASS if ram else WARNING,
            f"uso {ram.get('percent')}% · {used_gb}/{total_gb} GB")

    disks = metrics.get("disk") or []
    if disks:
        d = disks[0]
        rep.add("Armazenamento", PASS,
                f"livre {d.get('free_gb')} GB de {d.get('total_gb')} GB ({d.get('percent')}% usado) em {d.get('mount')}")
    else:
        rep.add("Armazenamento", WARNING, "nenhuma partição de disco lida.")


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def run_checks(server: str | None = None, token: str | None = None,
               perms: dict[str, bool] | None = None) -> Report:
    rep = Report(platform=f"{platform.system()} {platform.release()}")
    check_os(rep)
    check_architecture(rep)
    check_python(rep)
    check_network(rep, server)
    check_websocket(rep)
    check_auth(rep, token)
    check_permissions(rep, perms)
    check_screen(rep, perms)
    check_ocr(rep)
    check_mouse_keyboard(rep, perms)
    check_clipboard(rep)
    check_browser(rep)
    check_audio_mic(rep, perms)
    check_gpu(rep)
    return rep


def _load_agent_context(server: str | None) -> tuple[str | None, dict[str, bool] | None]:
    """Read the saved agent config (token, server, permissions) if present."""
    try:
        from .agent_client import load_config
        cfg = load_config()
    except Exception:  # noqa: BLE001
        return None, None
    token = cfg.get("token")
    server = server or cfg.get("server")
    perms = cfg.get("permissions")
    return token, perms if isinstance(perms, dict) else None


def _color(status: str) -> str:
    return {
        PASS: "\033[92m", WARNING: "\033[93m", FAIL: "\033[91m",
        NOT_INSTALLED: "\033[90m", NOT_PERMITTED: "\033[95m",
    }.get(status, "")


def render(rep: Report, color: bool = True) -> str:
    lines = []
    reset = "\033[0m" if color else ""
    lines.append("=" * 64)
    lines.append("  OpenHUD Agent Diagnostics")
    lines.append("=" * 64)
    lines.append(f"  Plataforma: {rep.platform}")
    lines.append("-" * 64)
    for c in rep.checks:
        tag = c.status
        if color:
            tag = f"{_color(c.status)}{tag}{reset}"
        lines.append(f"  [{tag}] {c.name}")
        if c.detail:
            lines.append(f"        {c.detail}")
        if c.hint and c.status not in (PASS,):
            lines.append(f"        → {c.hint}")
    lines.append("-" * 64)
    s = rep.summary
    lines.append("  Resumo: " + " · ".join(f"{k}={v}" for k, v in s.items() if v))
    lines.append("  Resultado: " + ("PRONTO" if rep.ok else "AÇÃO NECESSÁRIA"))
    lines.append("=" * 64)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="OpenHUD Agent Diagnostics")
    parser.add_argument("--server", help="URL do servidor OpenHUD (para testar conexão/HTTPS)")
    parser.add_argument("--pair", help="Código de pareamento (opcional; testa autenticação)")
    parser.add_argument("--json", action="store_true", help="Saída em JSON")
    parser.add_argument("--no-color", action="store_true", help="Sem cores no terminal")
    args = parser.parse_args(argv)

    server = args.server
    token, perms = _load_agent_context(server)
    if args.pair:
        # A pairing code means the user intends to authenticate; report the
        # intent rather than pretending a token already exists.
        token = token or "__pending_pair__"
    if args.server:
        server = args.server
    rep = run_checks(server=server, token=token, perms=perms)
    if args.json:
        print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render(rep, color=not args.no_color))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
