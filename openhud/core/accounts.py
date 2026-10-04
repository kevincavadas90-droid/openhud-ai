"""User accounts for OpenHUD AI: registration, login, sessions and devices.

This is the multi-user layer that sits alongside the single-operator
``AuthManager`` (which still protects the local/desktop instance). It is built
on the existing database abstraction, so it works identically on SQLite and
PostgreSQL.

Security properties:
  * passwords are stored only as PBKDF2-HMAC-SHA256 hashes with a per-user salt
    and a constant-time comparison — never in clear text;
  * session and reset tokens are random and stored only as SHA-256 hashes, so a
    database leak does not expose usable credentials;
  * every mutating operation is explicit and parameterised (no string-built
    SQL), so there is no SQL-injection surface;
  * account existence is not leaked by the password-reset flow.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
import uuid
from typing import Any

PBKDF2_ITERATIONS = 210_000
SESSION_TTL = 60 * 60 * 24 * 30          # 30 days
RESET_TTL = 60 * 60                       # 1 hour
VERIFY_TTL = 60 * 60 * 24                 # 24 hours

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8

# A tiny list of the most common passwords, rejected at registration. This is
# a floor, not a full policy: it blocks the obvious cases without annoying real
# users.
COMMON_PASSWORDS = {
    "12345678", "123456789", "1234567890", "password", "senha123", "qwerty123",
    "11111111", "abc12345", "password1", "admin123", "openhud", "iloveyou",
}


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Return a self-describing PBKDF2 hash string (salt is embedded)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64e(salt)}${_b64e(digest)}"


def verify_password_hash(password: str, stored: str) -> bool:
    """Constant-time verification of a stored PBKDF2 hash string."""
    try:
        scheme, iter_s, salt_b64, digest_b64 = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        salt = _b64d(salt_b64)
        expected = _b64d(digest_b64)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> float:
    return time.time()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> bool:
    email = normalize_email(email)
    return bool(email) and len(email) <= 254 and bool(EMAIL_RE.match(email))


def validate_password(password: str) -> tuple[bool, str]:
    """Return (ok, reason). Reasons are user-facing and never echo the password."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return False, f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."
    if len(password) > 200:
        return False, "A senha é longa demais."
    if password.lower() in COMMON_PASSWORDS:
        return False, "Essa senha é muito comum. Escolha outra."
    if password.isdigit() or password.isalpha():
        return False, "Use uma mistura de letras e números."
    return True, ""


class AccountManager:
    """Persistence + logic for user accounts, sessions and linked devices."""

    def __init__(self, db) -> None:
        self.db = db

    # The database abstraction returns sqlite3.Row on SQLite and dict on
    # Postgres; normalise to dict so callers can use .get() uniformly.
    @staticmethod
    def _dict(row) -> dict[str, Any] | None:
        if row is None:
            return None
        return row if isinstance(row, dict) else dict(row)

    def _one(self, sql: str, params=()) -> dict[str, Any] | None:
        return self._dict(self.db.query_one(sql, params))

    def _all(self, sql: str, params=()) -> list[dict[str, Any]]:
        return [r if isinstance(r, dict) else dict(r) for r in self.db.query(sql, params)]

    # -- users -----------------------------------------------------------
    def create_user(self, email: str, password: str, name: str = "") -> dict[str, Any]:
        email = normalize_email(email)
        if not validate_email(email):
            raise ValueError("E-mail inválido.")
        ok, reason = validate_password(password)
        if not ok:
            raise ValueError(reason)
        if self.get_user_by_email(email) is not None:
            raise ValueError("Já existe uma conta com este e-mail.")
        uid = uuid.uuid4().hex
        now = _now()
        self.db.execute(
            "INSERT INTO users(id, email, name, password_hash, email_verified, status, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, 0, 'active', ?, ?)",
            (uid, email, (name or "").strip()[:80], hash_password(password), now, now),
        )
        return self.get_user(uid)  # type: ignore[return-value]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM users WHERE id=?", (user_id,))

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM users WHERE email=?", (normalize_email(email),))

    def verify_credentials(self, email: str, password: str) -> dict[str, Any] | None:
        """Return the user on success, else None. Always runs a hash to avoid
        leaking whether the e-mail exists via response timing."""
        user = self.get_user_by_email(email)
        stored = user["password_hash"] if user else hash_password("dummy-password-for-timing")
        ok = verify_password_hash(password, stored)
        if user and ok and user.get("status") == "active":
            return user
        return None

    def set_password(self, user_id: str, new_password: str) -> None:
        ok, reason = validate_password(new_password)
        if not ok:
            raise ValueError(reason)
        self.db.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
            (hash_password(new_password), _now(), user_id),
        )

    def change_password(self, user_id: str, current: str, new: str) -> None:
        user = self.get_user(user_id)
        if not user or not verify_password_hash(current, user["password_hash"]):
            raise ValueError("Senha atual incorreta.")
        self.set_password(user_id, new)

    def set_name(self, user_id: str, name: str) -> None:
        self.db.execute(
            "UPDATE users SET name=?, updated_at=? WHERE id=?",
            ((name or "").strip()[:80], _now(), user_id),
        )

    def mark_email_verified(self, user_id: str) -> None:
        self.db.execute(
            "UPDATE users SET email_verified=1, updated_at=? WHERE id=?",
            (_now(), user_id),
        )

    def touch_login(self, user_id: str) -> None:
        self.db.execute("UPDATE users SET last_login=? WHERE id=?", (_now(), user_id))

    def delete_user(self, user_id: str) -> None:
        """Delete the account and all data that belongs to it."""
        self.db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        self.db.execute("DELETE FROM password_resets WHERE user_id=?", (user_id,))
        self.db.execute("DELETE FROM email_verifications WHERE user_id=?", (user_id,))
        self.db.execute("DELETE FROM user_devices WHERE user_id=?", (user_id,))
        self.db.execute("DELETE FROM users WHERE id=?", (user_id,))

    def public_user(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name") or "",
            "email_verified": bool(user.get("email_verified")),
            "status": user.get("status", "active"),
            "created_at": user.get("created_at"),
            "last_login": user.get("last_login"),
        }

    # -- sessions --------------------------------------------------------
    def create_session(self, user_id: str, user_agent: str = "", ip: str = "") -> tuple[str, dict[str, Any]]:
        raw = secrets.token_urlsafe(32)
        sid = uuid.uuid4().hex
        now = _now()
        self.db.execute(
            "INSERT INTO user_sessions(id, user_id, token_hash, created_at, expires_at, last_seen, user_agent, ip) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, user_id, _hash_token(raw), now, now + SESSION_TTL, now,
             (user_agent or "")[:300], (ip or "")[:64]),
        )
        return raw, {"id": sid, "expires_at": now + SESSION_TTL}

    def resolve_session(self, token: str | None) -> dict[str, Any] | None:
        """Return the session row joined with the user, or None if invalid."""
        if not token:
            return None
        row = self._one("SELECT * FROM user_sessions WHERE token_hash=?", (_hash_token(token),))
        if row is None:
            return None
        if float(row["expires_at"]) < _now():
            self.db.execute("DELETE FROM user_sessions WHERE id=?", (row["id"],))
            return None
        return row

    def user_for_session(self, token: str | None) -> dict[str, Any] | None:
        row = self.resolve_session(token)
        if row is None:
            return None
        user = self.get_user(row["user_id"])
        if user is None or user.get("status") != "active":
            return None
        self.db.execute("UPDATE user_sessions SET last_seen=? WHERE id=?", (_now(), row["id"]))
        return user

    def revoke_session(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM user_sessions WHERE token_hash=?", (_hash_token(token),))

    def revoke_all_sessions(self, user_id: str) -> None:
        self.db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT id, created_at, expires_at, last_seen, user_agent, ip "
            "FROM user_sessions WHERE user_id=? ORDER BY last_seen DESC",
            (user_id,),
        )

    # -- password reset --------------------------------------------------
    def create_reset(self, user_id: str) -> str:
        raw = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO password_resets(id, user_id, token_hash, created_at, expires_at, used) "
            "VALUES(?, ?, ?, ?, ?, 0)",
            (uuid.uuid4().hex, user_id, _hash_token(raw), _now(), _now() + RESET_TTL),
        )
        return raw

    def consume_reset(self, raw_token: str, new_password: str) -> str | None:
        """Reset the password and return the user id, or None if the token is
        invalid/expired. All other sessions are revoked on success."""
        row = self._one("SELECT * FROM password_resets WHERE token_hash=?", (_hash_token(raw_token or ""),))
        if row is None or row.get("used") or float(row["expires_at"]) < _now():
            return None
        self.set_password(row["user_id"], new_password)
        self.db.execute("UPDATE password_resets SET used=1 WHERE id=?", (row["id"],))
        self.revoke_all_sessions(row["user_id"])
        return row["user_id"]

    # -- e-mail verification --------------------------------------------
    def create_email_verification(self, user_id: str) -> str:
        raw = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO email_verifications(id, user_id, token_hash, created_at, expires_at, used) "
            "VALUES(?, ?, ?, ?, ?, 0)",
            (uuid.uuid4().hex, user_id, _hash_token(raw), _now(), _now() + VERIFY_TTL),
        )
        return raw

    def consume_email_verification(self, raw_token: str) -> str | None:
        row = self._one(
            "SELECT * FROM email_verifications WHERE token_hash=?", (_hash_token(raw_token or ""),)
        )
        if row is None or row.get("used") or float(row["expires_at"]) < _now():
            return None
        self.mark_email_verified(row["user_id"])
        self.db.execute("UPDATE email_verifications SET used=1 WHERE id=?", (row["id"],))
        return row["user_id"]

    # -- devices ---------------------------------------------------------
    def link_device(self, user_id: str, device_id: str, name: str = "") -> None:
        now = _now()
        existing = self._one(
            "SELECT device_id FROM user_devices WHERE user_id=? AND device_id=?", (user_id, device_id)
        )
        if existing:
            self.db.execute(
                "UPDATE user_devices SET name=? WHERE user_id=? AND device_id=?",
                (name or "", user_id, device_id),
            )
        else:
            self.db.execute(
                "INSERT INTO user_devices(user_id, device_id, name, linked_at) VALUES(?, ?, ?, ?)",
                (user_id, device_id, name or "", now),
            )

    def list_user_devices(self, user_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM user_devices WHERE user_id=? ORDER BY linked_at DESC", (user_id,)
        )

    def unlink_device(self, user_id: str, device_id: str) -> bool:
        existing = self._one(
            "SELECT device_id FROM user_devices WHERE user_id=? AND device_id=?", (user_id, device_id)
        )
        if not existing:
            return False
        self.db.execute("DELETE FROM user_devices WHERE user_id=? AND device_id=?", (user_id, device_id))
        return True

    def user_for_device(self, device_id: str) -> dict[str, Any] | None:
        row = self._one("SELECT user_id FROM user_devices WHERE device_id=?", (device_id,))
        if row is None:
            return None
        return self.get_user(row["user_id"])

    def owns_device(self, user_id: str, device_id: str) -> bool:
        return self._one(
            "SELECT device_id FROM user_devices WHERE user_id=? AND device_id=?", (user_id, device_id)
        ) is not None
