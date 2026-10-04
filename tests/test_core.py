"""Tests for core OpenHUD behavior. Run with: .venv/bin/pytest -q"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Isolate test data before importing the package.
_TMP = tempfile.mkdtemp(prefix="openhud-test-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["OPENHUD_WORKSPACE"] = str(Path(_TMP) / "workspace")

from openhud.core.crypto import SecretCipher  # noqa: E402
from openhud.core.db import Database  # noqa: E402
from openhud.core.secrets_store import SecretStore  # noqa: E402
from openhud.tools.base import ToolContext  # noqa: E402
from openhud.tools import build_default_registry  # noqa: E402
from openhud.config import settings  # noqa: E402


def make_ctx(db, secrets) -> ToolContext:
    return ToolContext(workspace_dir=settings.workspace_dir, settings=settings, secrets=secrets, db=db)


def test_crypto_roundtrip():
    cipher = SecretCipher(Path(_TMP) / "k.key")
    token = cipher.encrypt("super-secret-value")
    assert token != b"super-secret-value"
    assert cipher.decrypt(token) == "super-secret-value"


def test_secret_store_masks():
    db = Database(Path(_TMP) / "s.db")
    store = SecretStore(db, SecretCipher(Path(_TMP) / "k2.key"))
    store.set("openai", "sk-abcdefghijklmnop")
    assert store.get("openai") == "sk-abcdefghijklmnop"
    masked = store.mask(store.get("openai"))
    assert "abcdefghij" not in masked
    assert masked.startswith("sk-a")


def test_database_conversation_flow():
    db = Database(Path(_TMP) / "c.db")
    conv = db.create_conversation(title="teste")
    db.add_message(conv["id"], "user", "olá")
    db.add_message(conv["id"], "assistant", "oi")
    msgs = db.list_messages(conv["id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert db.get_conversation(conv["id"])["title"] == "teste"


def test_memory_search():
    db = Database(Path(_TMP) / "m.db")
    db.add_memory("O usuário prefere respostas em português", "preferencia")
    hits = db.search_memories("português")
    assert len(hits) == 1
    assert "português" in hits[0]["content"]


def test_filesystem_tool_sandbox(tmp_path):
    db = Database(Path(_TMP) / "f.db")
    registry = build_default_registry()
    ctx = make_ctx(db, None)
    res = registry.execute("write_file", {"path": "sub/nota.txt", "content": "conteúdo"}, ctx)
    assert res.ok
    res = registry.execute("read_file", {"path": "sub/nota.txt"}, ctx)
    assert res.ok and res.output == "conteúdo"
    # Path traversal must be refused.
    res = registry.execute("read_file", {"path": "../../etc/passwd"}, ctx)
    assert not res.ok


def test_python_tool_runs():
    db = Database(Path(_TMP) / "p.db")
    registry = build_default_registry()
    ctx = make_ctx(db, None)
    res = registry.execute("run_python", {"code": "print(6*7)"}, ctx)
    assert res.ok
    assert "42" in res.output


def test_shell_tool_blocks_destructive():
    db = Database(Path(_TMP) / "sh.db")
    registry = build_default_registry()
    ctx = make_ctx(db, None)
    res = registry.execute("run_shell", {"command": "rm -rf /"}, ctx)
    assert not res.ok
    assert "bloqueado" in res.output.lower()


def test_unknown_tool_returns_error():
    db = Database(Path(_TMP) / "u.db")
    registry = build_default_registry()
    ctx = make_ctx(db, None)
    res = registry.execute("does_not_exist", {}, ctx)
    assert not res.ok


def test_settings_persist(tmp_path):
    db = Database(Path(_TMP) / "set.db")
    db.set_setting("model", "gpt-4o")
    assert db.get_setting("model") == "gpt-4o"
    assert db.get_setting("missing", "default") == "default"


def test_analyze_data_tool():
    db = Database(Path(_TMP) / "d.db")
    registry = build_default_registry()
    ctx = make_ctx(db, None)
    registry.execute(
        "write_file",
        {"path": "vendas.csv", "content": "produto,valor\nA,10\nB,20\nC,30\n"},
        ctx,
    )
    res = registry.execute("analyze_data", {"path": "vendas.csv"}, ctx)
    assert res.ok
    assert "Linhas: 3" in res.output
    assert "valor" in res.output
    assert "média=20" in res.output


def test_task_lifecycle():
    db = Database(Path(_TMP) / "t.db")
    task = db.create_task("diario", "resuma as novidades", 60)
    assert task["enabled"] == 1
    assert len(db.list_tasks()) == 1
    db.set_task_enabled(task["id"], False)
    assert db.get_task(task["id"])["enabled"] == 0
    db.record_task_run(task["id"], "ok", "resultado")
    assert db.get_task(task["id"])["last_status"] == "ok"
    db.delete_task(task["id"])
    assert db.list_tasks() == []
