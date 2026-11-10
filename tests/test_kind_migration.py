"""kind 约束迁移脚本：dry-run SQL 完整性、执行门槛与事务行为（不连真实数据库）。"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_kind_migration.py"


def _load():
    spec = importlib.util.spec_from_file_location("kind_migration", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, env=env, check=False)


class _Cursor:
    def __init__(self, fail_at=None):
        self.sql = []
        self.fail_at = fail_at

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        if self.fail_at == len(self.sql) + 1:
            raise RuntimeError("synthetic failure")
        self.sql.append(sql)


class _Conn:
    def __init__(self, fail_at=None):
        self.cur = _Cursor(fail_at)
        self.committed = False
        self.rolled = False
        self.closed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled = True

    def close(self):
        self.closed = True


def test_dry_run_sql_contains_every_kind() -> None:
    from rag_tech_retriever.platform.record_store import RECORD_KINDS

    result = _run()
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
    assert result.stdout.count("ALTER TABLE") == 2
    assert all(f"'{kind}'" in result.stdout for kind in RECORD_KINDS)


def test_apply_requires_explicit_confirmation() -> None:
    result = _run("--apply")
    assert result.returncode == 1
    assert "FAIL" in result.stdout


def test_apply_runs_two_statements_in_one_transaction() -> None:
    module, conn = _load(), _Conn()
    module.apply_migration("dsn", "workspace_records", connect=lambda dsn: conn)
    assert len(conn.cur.sql) == 2
    assert conn.committed and conn.closed and not conn.rolled


def test_apply_rolls_back_on_failure() -> None:
    module, conn = _load(), _Conn(fail_at=2)
    with pytest.raises(RuntimeError):
        module.apply_migration("dsn", "workspace_records", connect=lambda dsn: conn)
    assert conn.rolled and not conn.committed and conn.closed
