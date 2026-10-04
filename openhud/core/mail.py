"""Outbound e-mail for account verification, password reset and alerts.

Configuration is entirely environment-driven — no credentials live in code:

    OPENHUD_SMTP_HOST      SMTP server host (e.g. smtp.gmail.com)
    OPENHUD_SMTP_PORT      port (default 587; 465 uses implicit TLS)
    OPENHUD_SMTP_USER      username
    OPENHUD_SMTP_PASSWORD  password / app password
    OPENHUD_SMTP_TLS       "starttls" (default), "ssl" or "none"
    OPENHUD_MAIL_FROM      From: address (default: no-reply@<host>)
    OPENHUD_PUBLIC_URL     base URL used to build links in e-mails

When no SMTP host is configured the module is honest about it: it does not
pretend to send. It records the message to ``data/outbox`` (useful for local
testing and for operators who copy the link manually) and reports
``delivered=False`` with a clear reason. The account API surfaces that state so
the user is never told an e-mail was sent when it was not.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger("openhud.mail")


@dataclass
class MailResult:
    delivered: bool
    transport: str          # "smtp" | "outbox" | "disabled"
    detail: str = ""

    def to_dict(self) -> dict:
        return {"delivered": self.delivered, "transport": self.transport, "detail": self.detail}


def smtp_configured() -> bool:
    return bool(os.environ.get("OPENHUD_SMTP_HOST"))


def public_url() -> str:
    return os.environ.get("OPENHUD_PUBLIC_URL", "").rstrip("/")


def _from_address() -> str:
    return os.environ.get("OPENHUD_MAIL_FROM") or "no-reply@openhud.local"


class Mailer:
    def __init__(self, data_dir: Path) -> None:
        self.outbox = Path(data_dir) / "outbox"
        self.outbox.mkdir(parents=True, exist_ok=True)

    def _write_outbox(self, to: str, subject: str, body: str) -> None:
        record = {"ts": time.time(), "to": to, "subject": subject, "body": body}
        name = f"{int(time.time() * 1000)}-{abs(hash(to)) % 100000}.json"
        try:
            (self.outbox / name).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def send(self, to: str, subject: str, body: str) -> MailResult:
        """Send an e-mail. Always writes a copy to the local outbox so the
        message is never lost, and reports honestly whether SMTP delivered it."""
        self._write_outbox(to, subject, body)

        host = os.environ.get("OPENHUD_SMTP_HOST")
        if not host:
            return MailResult(False, "outbox",
                              "SMTP não configurado; mensagem gravada em data/outbox.")

        port = int(os.environ.get("OPENHUD_SMTP_PORT", "587"))
        user = os.environ.get("OPENHUD_SMTP_USER", "")
        password = os.environ.get("OPENHUD_SMTP_PASSWORD", "")
        mode = os.environ.get("OPENHUD_SMTP_TLS", "starttls").lower()

        msg = EmailMessage()
        msg["From"] = _from_address()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            if mode == "ssl":
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as srv:
                    if user:
                        srv.login(user, password)
                    srv.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=15) as srv:
                    if mode != "none":
                        srv.starttls(context=ssl.create_default_context())
                    if user:
                        srv.login(user, password)
                    srv.send_message(msg)
        except Exception as exc:  # noqa: BLE001 - report the real error, never swallow
            log.warning("Falha ao enviar e-mail para %s: %s", to, exc)
            return MailResult(False, "smtp", f"{type(exc).__name__}: {exc}")

        return MailResult(True, "smtp", "Enviado.")


def verification_email(name: str, link: str) -> tuple[str, str]:
    subject = "Confirme seu e-mail no OpenHUD AI"
    body = (
        f"Olá{', ' + name if name else ''}!\n\n"
        "Confirme seu e-mail para ativar todos os recursos da sua conta OpenHUD AI.\n\n"
        f"{link}\n\n"
        "O link expira em 24 horas. Se você não criou esta conta, ignore esta mensagem.\n\n"
        "— Equipe OpenHUD AI"
    )
    return subject, body


def reset_email(name: str, link: str) -> tuple[str, str]:
    subject = "Redefinição de senha do OpenHUD AI"
    body = (
        f"Olá{', ' + name if name else ''}!\n\n"
        "Recebemos um pedido para redefinir a senha da sua conta OpenHUD AI.\n\n"
        f"{link}\n\n"
        "O link expira em 1 hora. Se não foi você, ignore esta mensagem — sua senha "
        "continua a mesma.\n\n"
        "— Equipe OpenHUD AI"
    )
    return subject, body
