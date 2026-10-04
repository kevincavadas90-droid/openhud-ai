"""PostgreSQL backend, used when DATABASE_URL is set.

Mirrors the :class:`openhud.core.db.Database` interface so the rest of the
application is unaware of which engine is in use. Only psycopg is needed at
runtime, and only when a Postgres URL is configured.

The SQLite backend is the default and remains fully supported; Postgres is
for deployments that need a database which outlives the application
container (e.g. Neon, Supabase, Aiven free tiers).
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterable

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS secrets (
        name TEXT PRIMARY KEY, value BYTEA NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        created_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY, project_id TEXT, title TEXT NOT NULL DEFAULT 'Nova conversa',
        created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '', tool_calls TEXT, created_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY, content TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
        created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS activities (
        id TEXT PRIMARY KEY, conversation_id TEXT, kind TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '', created_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL,
        interval_seconds INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        next_run DOUBLE PRECISION NOT NULL, last_run DOUBLE PRECISION,
        last_status TEXT, last_result TEXT, created_at DOUBLE PRECISION NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_activities_conv ON activities(conversation_id, created_at)",
    """CREATE TABLE IF NOT EXISTS experiences (
        id TEXT PRIMARY KEY, action TEXT NOT NULL, context TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '', success INTEGER NOT NULL DEFAULT 0,
        feedback TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '',
        created_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'QUEUED',
        progress INTEGER NOT NULL DEFAULT 0, params TEXT NOT NULL DEFAULT '{}',
        logs TEXT NOT NULL DEFAULT '', result TEXT, error TEXT,
        created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_jobs_kind ON jobs(kind, created_at)",
    """CREATE TABLE IF NOT EXISTS plugins (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL DEFAULT '0.0.0',
        author TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'native', risk TEXT NOT NULL DEFAULT 'SAFE',
        permissions TEXT NOT NULL DEFAULT '[]', enabled INTEGER NOT NULL DEFAULT 1,
        builtin INTEGER NOT NULL DEFAULT 0,
        created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS voice_history (
        id TEXT PRIMARY KEY, conversation_id TEXT, transcript TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'stt',
        created_at DOUBLE PRECISION NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_voice_conv ON voice_history(conversation_id, created_at)",
    """CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL, email_verified INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active', created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL, last_login DOUBLE PRECISION)""",
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
    """CREATE TABLE IF NOT EXISTS user_sessions (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
        created_at DOUBLE PRECISION NOT NULL, expires_at DOUBLE PRECISION NOT NULL,
        last_seen DOUBLE PRECISION NOT NULL, user_agent TEXT NOT NULL DEFAULT '',
        ip TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(token_hash)",
    """CREATE TABLE IF NOT EXISTS password_resets (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
        created_at DOUBLE PRECISION NOT NULL, expires_at DOUBLE PRECISION NOT NULL,
        used INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS idx_resets_token ON password_resets(token_hash)",
    """CREATE TABLE IF NOT EXISTS email_verifications (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
        created_at DOUBLE PRECISION NOT NULL, expires_at DOUBLE PRECISION NOT NULL,
        used INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS idx_verify_token ON email_verifications(token_hash)",
    """CREATE TABLE IF NOT EXISTS user_devices (
        user_id TEXT NOT NULL, device_id TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
        linked_at DOUBLE PRECISION NOT NULL, PRIMARY KEY (user_id, device_id))""",
    "CREATE INDEX IF NOT EXISTS idx_userdevices_device ON user_devices(device_id)",
]


def _new_id() -> str:
    return uuid.uuid4().hex


def _translate(sql: str) -> str:
    """SQLite uses ``?`` placeholders; Postgres uses ``%s``."""
    return sql.replace("?", "%s")


class PostgresDatabase:
    def __init__(self, url: str) -> None:
        import psycopg  # imported lazily so SQLite users need not install it

        self.url = url
        self._psycopg = psycopg
        self._init_schema()

    def _connect(self):
        return self._psycopg.connect(self.url, autocommit=True)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                for stmt in SCHEMA_STATEMENTS:
                    cur.execute(stmt)

    # -- generic helpers -------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(_translate(sql), tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(_translate(sql), tuple(params))
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # -- settings --------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
            (key, json.dumps(value)),
        )

    def all_settings(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self.query("SELECT key, value FROM settings")}

    # -- secrets ---------------------------------------------------------
    def set_secret(self, name: str, value: bytes) -> None:
        self.execute(
            "INSERT INTO secrets(name, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            (name, value, time.time()),
        )

    def get_secret(self, name: str) -> bytes | None:
        row = self.query_one("SELECT value FROM secrets WHERE name=?", (name,))
        return bytes(row["value"]) if row else None

    def delete_secret(self, name: str) -> None:
        self.execute("DELETE FROM secrets WHERE name=?", (name,))

    def secret_names(self) -> list[str]:
        return [r["name"] for r in self.query("SELECT name FROM secrets ORDER BY name")]

    # -- projects --------------------------------------------------------
    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        pid, now = _new_id(), time.time()
        self.execute(
            "INSERT INTO projects(id, name, description, created_at) VALUES(?, ?, ?, ?)",
            (pid, name, description, now),
        )
        return {"id": pid, "name": name, "description": description, "created_at": now}

    def list_projects(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM projects ORDER BY created_at DESC")

    def delete_project(self, pid: str) -> None:
        self.execute("DELETE FROM projects WHERE id=?", (pid,))

    # -- conversations ---------------------------------------------------
    def create_conversation(self, project_id: str | None = None, title: str = "Nova conversa") -> dict[str, Any]:
        cid, now = _new_id(), time.time()
        self.execute(
            "INSERT INTO conversations(id, project_id, title, created_at, updated_at) VALUES(?, ?, ?, ?, ?)",
            (cid, project_id, title, now, now),
        )
        return {"id": cid, "project_id": project_id, "title": title, "created_at": now, "updated_at": now}

    def list_conversations(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            return self.query(
                "SELECT * FROM conversations WHERE project_id=? ORDER BY updated_at DESC", (project_id,)
            )
        return self.query("SELECT * FROM conversations ORDER BY updated_at DESC")

    def get_conversation(self, cid: str) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM conversations WHERE id=?", (cid,))

    def touch_conversation(self, cid: str, title: str | None = None) -> None:
        if title:
            self.execute("UPDATE conversations SET updated_at=?, title=? WHERE id=?", (time.time(), title, cid))
        else:
            self.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), cid))

    def delete_conversation(self, cid: str) -> None:
        self.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        self.execute("DELETE FROM conversations WHERE id=?", (cid,))

    # -- messages --------------------------------------------------------
    def add_message(self, conversation_id: str, role: str, content: str, tool_calls: Any = None) -> dict[str, Any]:
        mid, now = _new_id(), time.time()
        self.execute(
            "INSERT INTO messages(id, conversation_id, role, content, tool_calls, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (mid, conversation_id, role, content, json.dumps(tool_calls) if tool_calls else None, now),
        )
        return {"id": mid, "conversation_id": conversation_id, "role": role,
                "content": content, "tool_calls": tool_calls, "created_at": now}

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self.query(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (conversation_id,)
        )
        for d in rows:
            d["tool_calls"] = json.loads(d["tool_calls"]) if d["tool_calls"] else None
        return rows

    # -- memories --------------------------------------------------------
    def add_memory(self, content: str, tags: str = "") -> dict[str, Any]:
        mid, now = _new_id(), time.time()
        self.execute(
            "INSERT INTO memories(id, content, tags, created_at, updated_at) VALUES(?, ?, ?, ?, ?)",
            (mid, content, tags, now, now),
        )
        return {"id": mid, "content": content, "tags": tags, "created_at": now, "updated_at": now}

    def list_memories(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM memories ORDER BY updated_at DESC")

    def update_memory(self, mid: str, content: str, tags: str) -> None:
        self.execute(
            "UPDATE memories SET content=?, tags=?, updated_at=? WHERE id=?",
            (content, tags, time.time(), mid),
        )

    def delete_memory(self, mid: str) -> None:
        self.execute("DELETE FROM memories WHERE id=?", (mid,))

    def search_memories(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        like = f"%{query}%"
        return self.query(
            "SELECT * FROM memories WHERE content ILIKE ? OR tags ILIKE ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (like, like, limit),
        )

    # -- activities ------------------------------------------------------
    def add_activity(self, kind: str, detail: str = "", conversation_id: str | None = None) -> dict[str, Any]:
        aid, now = _new_id(), time.time()
        self.execute(
            "INSERT INTO activities(id, conversation_id, kind, detail, created_at) VALUES(?, ?, ?, ?, ?)",
            (aid, conversation_id, kind, detail, now),
        )
        return {"id": aid, "conversation_id": conversation_id, "kind": kind,
                "detail": detail, "created_at": now}

    def list_activities(self, conversation_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if conversation_id:
            return self.query(
                "SELECT * FROM activities WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit),
            )
        return self.query("SELECT * FROM activities ORDER BY created_at DESC LIMIT ?", (limit,))

    # -- scheduled tasks -------------------------------------------------
    def create_task(self, name: str, prompt: str, interval_seconds: int) -> dict[str, Any]:
        tid, now = _new_id(), time.time()
        self.execute(
            "INSERT INTO tasks(id, name, prompt, interval_seconds, enabled, next_run, created_at) "
            "VALUES(?, ?, ?, ?, 1, ?, ?)",
            (tid, name, prompt, interval_seconds, now + interval_seconds, now),
        )
        return self.get_task(tid)

    def get_task(self, tid: str) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM tasks WHERE id=?", (tid,))

    def list_tasks(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM tasks ORDER BY created_at DESC")

    def set_task_enabled(self, tid: str, enabled: bool) -> None:
        self.execute("UPDATE tasks SET enabled=? WHERE id=?", (1 if enabled else 0, tid))

    def delete_task(self, tid: str) -> None:
        self.execute("DELETE FROM tasks WHERE id=?", (tid,))

    def due_tasks(self, now: float) -> list[dict[str, Any]]:
        return self.query(
            "SELECT * FROM tasks WHERE enabled=1 AND next_run<=? ORDER BY next_run", (now,)
        )

    def record_task_run(self, tid: str, status: str, result: str) -> None:
        task = self.get_task(tid)
        if not task:
            return
        now = time.time()
        self.execute(
            "UPDATE tasks SET last_run=?, last_status=?, last_result=?, next_run=? WHERE id=?",
            (now, status, result[:2000], now + int(task["interval_seconds"]), tid),
        )

    # -- voice history ---------------------------------------------------
    def add_voice_history(self, transcript: str, language: str = "",
                          kind: str = "stt", conversation_id: str | None = None) -> dict[str, Any]:
        vid, now = _new_id(), time.time()
        self.execute(
            "INSERT INTO voice_history(id, conversation_id, transcript, language, kind, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (vid, conversation_id, transcript, language, kind, now),
        )
        return {"id": vid, "conversation_id": conversation_id, "transcript": transcript,
                "language": language, "kind": kind, "created_at": now}

    def list_voice_history(self, conversation_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if conversation_id:
            return self.query(
                "SELECT * FROM voice_history WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit),
            )
        return self.query("SELECT * FROM voice_history ORDER BY created_at DESC LIMIT ?", (limit,))

    def delete_voice_history(self, vid: str | None = None) -> int:
        if vid:
            self.execute("DELETE FROM voice_history WHERE id=?", (vid,))
            return 1
        rows = self.query("SELECT COUNT(*) AS n FROM voice_history")
        self.execute("DELETE FROM voice_history")
        return int(rows[0]["n"]) if rows else 0
