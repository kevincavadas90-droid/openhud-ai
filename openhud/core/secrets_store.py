"""High-level secret store: encrypts values before persisting them.

API keys are addressed by name (e.g. "openai", "anthropic", "brave").
Only a masked preview is ever returned to the UI.
"""
from __future__ import annotations

from .crypto import SecretCipher
from .db import Database


class SecretStore:
    def __init__(self, db: Database, cipher: SecretCipher) -> None:
        self.db = db
        self.cipher = cipher

    def set(self, name: str, value: str) -> None:
        self.db.set_secret(name, self.cipher.encrypt(value))

    def get(self, name: str) -> str | None:
        token = self.db.get_secret(name)
        return self.cipher.decrypt(token) if token else None

    def delete(self, name: str) -> None:
        self.db.delete_secret(name)

    def names(self) -> list[str]:
        return self.db.secret_names()

    @staticmethod
    def mask(value: str | None) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "•" * len(value)
        return f"{value[:4]}{'•' * 8}{value[-4:]}"
