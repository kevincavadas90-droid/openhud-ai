"""Authentication for the public deployment.

The whole app sits behind a single-operator password so the agent is never
reachable anonymously. The password comes from ``OPENHUD_PASSWORD`` (never
hard-coded); if it is missing we generate a strong random one at startup and
print it once to the server log. Sessions are stateless signed cookies
(HMAC-SHA256) so no session table is needed and redeploys stay logged in as
long as the signing secret is stable.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

log = logging.getLogger("openhud.auth")

COOKIE_NAME = "openhud_session"
SESSION_TTL = 60 * 60 * 24 * 7  # 7 days


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def hash_password(password: str, salt: bytes) -> str:
    """PBKDF2-HMAC-SHA256, 200k iterations, compared in constant time."""
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return _b64e(digest)


class AuthManager:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = os.environ.get("OPENHUD_AUTH", "on").lower() not in {"off", "0", "false"}

        self._secret = self._load_secret()
        self._salt = self._load_salt()
        self._password_hash, self.generated_password = self._resolve_password()

    # -- setup -----------------------------------------------------------
    def _load_secret(self) -> bytes:
        env = os.environ.get("OPENHUD_SESSION_SECRET")
        if env:
            return env.encode("utf-8")
        path = self.data_dir / "session.key"
        if path.exists():
            return path.read_bytes().strip()
        key = secrets.token_bytes(32)
        path.write_bytes(key)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key

    def _load_salt(self) -> bytes:
        path = self.data_dir / "session.salt"
        if path.exists():
            return path.read_bytes().strip()
        salt = secrets.token_bytes(16)
        path.write_bytes(salt)
        return salt

    def _resolve_password(self) -> tuple[str | None, str | None]:
        env_pw = os.environ.get("OPENHUD_PASSWORD")
        if env_pw:
            return hash_password(env_pw, self._salt), None
        if not self.enabled:
            return None, None
        generated = secrets.token_urlsafe(12)
        log.warning(
            "OPENHUD_PASSWORD nao definido. Senha temporaria gerada: %s "
            "(defina OPENHUD_PASSWORD para uma senha fixa).",
            generated,
        )
        return hash_password(generated, self._salt), generated

    # -- verification ----------------------------------------------------
    def verify_password(self, password: str) -> bool:
        if not self.enabled:
            return True
        if self._password_hash is None:
            return False
        candidate = hash_password(password, self._salt)
        return hmac.compare_digest(candidate, self._password_hash)

    def issue_token(self) -> str:
        payload = {"exp": int(time.time()) + SESSION_TTL, "n": secrets.token_hex(8)}
        body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        sig = _b64e(hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{sig}"

    def verify_token(self, token: str | None) -> bool:
        if not self.enabled:
            return True
        if not token or "." not in token:
            return False
        body, sig = token.rsplit(".", 1)
        expected = _b64e(hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return False
        try:
            payload = json.loads(_b64d(body))
        except (ValueError, json.JSONDecodeError):
            return False
        return int(payload.get("exp", 0)) > time.time()
