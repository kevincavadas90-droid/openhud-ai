"""First-run setup wizard for the OpenHUD desktop app.

Pure and testable: it takes an ``io`` object with ``ask``/``say`` methods so the
flow can be exercised in tests without a real terminal. It explains what
OpenHUD is, collects the server URL and pairing code, explains each permission
group and lets the user opt in, and saves the result. It never enables
computer control silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .config import PERMISSION_GROUPS, DesktopConfig

INTRO = """\
OpenHUD AI é um assistente inteligente para o seu computador.

Ele conversa por texto e voz, ajuda a navegar na internet e, quando você
autorizar, pode ver a tela e agir no computador (mouse, teclado, aplicativos).

Nada de controle do computador é ativado sem a sua autorização explícita, e
você pode revogar qualquer permissão depois.
"""


class IO(Protocol):
    def say(self, message: str) -> None: ...
    def ask(self, prompt: str, default: str = "") -> str: ...
    def confirm(self, prompt: str, default: bool = False) -> bool: ...


@dataclass
class ConsoleIO:
    """Minimal console implementation of :class:`IO`."""

    out: Callable[[str], None] = print

    def say(self, message: str) -> None:
        self.out(message)

    def ask(self, prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        try:
            value = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            return default
        return value or default

    def confirm(self, prompt: str, default: bool = False) -> bool:
        hint = "S/n" if default else "s/N"
        try:
            value = input(f"{prompt} ({hint}): ").strip().lower()
        except EOFError:
            return default
        if not value:
            return default
        return value in {"s", "sim", "y", "yes", "1", "true"}


def run_wizard(config: DesktopConfig, io: IO, pair_code: str | None = None,
               login: Callable[[str, str, str, str], Any] | None = None) -> DesktopConfig:
    io.say("=" * 60)
    io.say("  OpenHUD AI — Assistente de configuração (primeira execução)")
    io.say("=" * 60)
    io.say(INTRO)

    # 1. Server
    io.say("\n1) Servidor")
    io.say("Informe o endereço do servidor OpenHUD (ex.: https://meu-servidor.exemplo).")
    server = io.ask("Servidor", config.server or "http://127.0.0.1:8000")
    config.server = server.rstrip("/")

    # 2. Sign in with the account (preferred) or pair with a code.
    # When no network helper is injected (offline / tests), keep the original
    # pairing flow so nothing regresses.
    use_account = False
    if login is not None:
        io.say("\n2) Sua conta")
        io.say("Entre com o mesmo e-mail e senha que você usa no site.")
        use_account = io.confirm("Entrar com e-mail e senha?", not bool(pair_code))
    if use_account:
        email = io.ask("E-mail", config.account_email)
        password = io.ask("Senha", "")
        device_name = io.ask("Nome deste computador", config.name or "Meu PC")
        config.name = device_name
        result = login(config.server, email, password, device_name, "windows")
        if getattr(result, "ok", False):
            config.token = result.token
            config.device_id = result.device_id
            config.account_email = (result.user or {}).get("email", email)
            config.account_name = (result.user or {}).get("name", "")
            io.say("Login realizado. Computador registrado na sua conta.")
        else:
            io.say(f"Não foi possível entrar: {getattr(result, 'message', 'erro')}")
            io.say("Você pode tentar de novo depois em 'Minha conta' no aplicativo.")
    else:
        io.say("\n2) Pareamento")
        io.say("No site, abra 'Painel do PC' e gere um código de pareamento de 6 dígitos.")
        if pair_code:
            code = pair_code
            io.say(f"Usando o código informado: {code}")
        else:
            code = io.ask("Código de pareamento (deixe vazio para usar um token existente)",
                          config.extra.get("pair_code", ""))
        if code:
            config.extra["pair_code"] = code
        else:
            token = io.ask("Token do dispositivo", config.token)
            if token:
                config.token = token

    # 3. Permissions
    io.say("\n3) Permissões")
    io.say("Escolha o que o OpenHUD pode usar. Você pode mudar isso depois.")
    for group, spec in PERMISSION_GROUPS.items():
        io.say(f"\n  {spec['label']}: {spec['description']}")
        current = config.groups.get(group, False)
        config.groups[group] = io.confirm(f"  Permitir '{spec['label']}'?", current)

    # 4. Startup
    io.say("\n4) Inicialização")
    config.autostart = io.confirm(
        "Iniciar o OpenHUD automaticamente com o Windows? (opcional)", config.autostart)

    config.onboarded = True
    config.save()
    io.say("\nConfiguração salva.")
    io.say(f"Permissões ativas: {config.summary()}")
    io.say("Conectando ao servidor…")
    return config
