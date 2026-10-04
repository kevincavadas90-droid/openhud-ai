"""Symmetric encryption for stored secrets (API keys, tokens).

A Fernet key is generated on first use and stored with 0600 permissions in
the data directory. Secrets are encrypted at rest in the SQLite database and
never written to logs or returned in full by the API.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretCipher:
    def __init__(self, key_path: Path) -> None:
        self.key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(key)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:  # pragma: no cover - corrupt store
            raise ValueError("Stored secret could not be decrypted") from exc
