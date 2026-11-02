"""Real owned PostgreSQL schema/role assertions; never touch an existing user database."""

import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.config_loader import ConfigError, ConfigLoader
from rag_tech_retriever.common.schema_policy import resolve_schema_mode, schema_timeouts
from rag_tech_retriever.platform import workspace_schema
from rag_tech_retriever.platform.record_store import RECORD_KINDS, RecordStore, StorageError
from rag_tech_retriever.platform.workspace_schema import managed_kind_check

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("profile,requested,expected", [("local", "", "auto"), ("local", "verify", "verify"), ("production", "", "verify"), ("production", "verify", "verify")])
def test_mode_contract(profile, requested, expected):
    assert resolve_schema_mode(profile, requested) == expected


@pytest.mark.parametrize("profile,requested", [("production", "auto"), ("production", "typo"), ("wrong", "verify"), ("local", " AUTO ")])
def test_production_cannot_opt_back_into_ddl(profile, requested):
    with pytest.raises(ConfigError): resolve_schema_mode(profile, requested)


def test_kind_expression_is_not_a_bag_of_valid_names():
    expression = "(kind = ANY (ARRAY['knowledge'::text, 'plan'::text]))"
    assert managed_kind_check(expression, {"knowledge", "plan"})
    for bad in [expression + " OR true", expression + " AND kind='knowledge'", "NOT " + expression,
                "(kind = ANY (ARRAY['knowledge'::text,'plan'::text,'other'::text]))"]:
        assert not managed_kind_check(bad, {"knowledge", "plan"})


@pytest.mark.parametrize("value", [True, 0, 10001, "3000"])
def test_schema_timeout_is_bounded_configuration(tmp_path, value):
    (tmp_path / "settings.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "web.yaml").write_text("operations:\n  schema_verify_timeout_ms: " + json.dumps(value), encoding="utf-8")
    with pytest.raises(ConfigError): schema_timeouts(ConfigLoader(tmp_path / "settings.yaml", tmp_path / "no.env"))


@pytest.mark.parametrize("backend", ["native", "docker"])
def test_full_release_gate_does_not_inherit_diagnostic_selection(tmp_path, monkeypatch, backend):
    spec = importlib.util.spec_from_file_location("native_gate_filter_test", ROOT / "scripts/release_gate.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, "configuration_report", lambda *a: {"passed": True, "checks": []})
    monkeypatch.setattr(module, "source_manifest", lambda root: {"fixture.py": "fixture"})
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k nonexistent -x")
    seen, commands = [], []
    def run(command, **kwargs):
        seen.append(kwargs["env"]["PYTEST_ADDOPTS"])
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "fixture boundary only", "")
    monkeypatch.setattr(module.subprocess, "run", run)
    args = ["release_gate.py", "--root", str(tmp_path), "--checks", "full", "--backend", backend,
            "--report", str(tmp_path / "gate.json")]
    if backend == "native":
        args.extend(["--native-session", str(tmp_path / "operator-session.json")])
    monkeypatch.setattr(sys, "argv", args)
    assert module.main() == 0 and seen and set(seen) == {""}
    expected = "scripts/native_gate_client.py" if backend == "native" else "scripts/ci_verify.py"
    assert commands[-1][1] == expected


@pytest.fixture
def store():
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression" and os.environ.get("POSTGRES_HOST") == "127.0.0.1"
    value = RecordStore("qa_schema_" + uuid4().hex[:10]); value.ensure_schema()
    try: yield value
    finally:
        with value.transaction() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {value.versions}")
            cur.execute(f"DROP TABLE IF EXISTS {value.records} CASCADE")
            cur.execute(f"DROP TABLE IF EXISTS {value.prefix}_other")


def state(store):
    """Hash exact catalog facts plus every extant row/version, including bad layouts."""
    with store.transaction() as cur:
        names = [store.records, store.versions]
        cur.execute("SELECT conname,contype,convalidated,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid=ANY(ARRAY[to_regclass(%s),to_regclass(%s)]) ORDER BY conname", names)
        values = [cur.fetchall()]
        cur.execute("SELECT attrelid,attname,attnotnull,atttypid,attnum FROM pg_attribute WHERE attrelid=ANY(ARRAY[to_regclass(%s),to_regclass(%s)]) AND attnum>0 ORDER BY attrelid,attnum", names)
        values.append(cur.fetchall())
        for name in names:
            cur.execute("SELECT to_regclass(%s) AS relation", (name,))
            if cur.fetchone()["relation"]:
                cur.execute(f"SELECT row_to_json(t) AS data FROM {name} t ORDER BY row_to_json(t)::text")
                values.append(cur.fetchall())
    return hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()


def replace_check(store, expression, suffix=""):
    with store.transaction() as cur:
        cur.execute(f"ALTER TABLE {store.records} DROP CONSTRAINT {store.records}_kind_check")
        cur.execute(f"ALTER TABLE {store.records} ADD CONSTRAINT {store.records}_kind_check CHECK ({expression}) {suffix}")


def all_kinds():
    return "kind IN (" + ",".join("'"+name+"'" for name in sorted(RECORD_KINDS)) + ")"


def test_valid_schema_verification_is_readonly_and_local_old_upgrade_preserves_history(store):
    row = store.save("knowledge", {"title": "preserve", "content": "owned fixture"})
    before = state(store)
    assert store.verify_schema()["verified"] and state(store) == before
    replace_check(store, "kind IN ('knowledge','plan')")
    old = state(store)
    with pytest.raises(StorageError, match="kind约束"): store.verify_schema()
    assert state(store) == old
    store.ensure_schema()
    assert store.get(row["id"])["data"] == row["data"] and len(store.history(row["id"])) == 1
    upgraded = state(store); store.ensure_schema(); assert state(store) == upgraded


@pytest.mark.parametrize("bad", ["old", "or_true", "and_restrict", "not_valid", "extra", "wrong_type", "missing_pk", "missing_default", "missing_history", "rls", "wrong_fk", "inheritance"])
def test_bad_schema_fails_without_repair_or_data_changes(store, bad):
    if bad in {"old", "or_true", "and_restrict", "not_valid"}:
        expression = "kind IN ('knowledge','plan')" if bad == "old" else all_kinds()
        if bad == "or_true": expression += " OR true"
        if bad == "and_restrict": expression += " AND kind='knowledge'"
        replace_check(store, expression, "NOT VALID" if bad == "not_valid" else "")
    else:
        with store.transaction() as cur:
            if bad == "extra": cur.execute(f"ALTER TABLE {store.records} ADD CONSTRAINT old_only CHECK(kind IN ('knowledge','plan'))")
            if bad == "wrong_type": cur.execute(f"ALTER TABLE {store.records} ALTER COLUMN data TYPE text USING data::text")
            if bad == "missing_pk": cur.execute(f"ALTER TABLE {store.versions} DROP CONSTRAINT {store.versions}_pkey")
            if bad == "missing_default": cur.execute(f"ALTER TABLE {store.versions} ALTER COLUMN created_at DROP DEFAULT")
            if bad == "missing_history": cur.execute(f"DROP TABLE {store.versions}")
            if bad == "rls": cur.execute(f"ALTER TABLE {store.records} ENABLE ROW LEVEL SECURITY")
            if bad == "inheritance":
                cur.execute(f"CREATE TABLE {store.prefix}_other(id text)")
                cur.execute(f"ALTER TABLE {store.records} INHERIT {store.prefix}_other")
            if bad == "wrong_fk":
                cur.execute(f"CREATE TABLE {store.prefix}_other(id text PRIMARY KEY)")
                cur.execute(f"ALTER TABLE {store.versions} DROP CONSTRAINT {store.versions}_record_id_fkey")
                cur.execute(f"ALTER TABLE {store.versions} ADD FOREIGN KEY(record_id) REFERENCES {store.prefix}_other(id)")
    before = state(store)
    with pytest.raises(StorageError): store.verify_schema()
    assert state(store) == before


def test_admin_migration_is_explicit_and_does_not_hide_missing_history(store):
    store.save("knowledge", {"title": "history required", "content": "owned fixture"})
    replace_check(store, "kind IN ('knowledge','plan')")
    before = state(store)
    with pytest.raises(StorageError): store.migrate_schema("yes")
    assert state(store) == before
    assert store.migrate_schema("仅创建或升级工作台结构，不删除记录")["records_deleted"] == 0
    with store.transaction() as cur: cur.execute(f"DROP TABLE {store.versions}")
    missing = state(store)
    with pytest.raises(StorageError, match="空历史"): store.migrate_schema("仅创建或升级工作台结构，不删除记录")
    assert state(store) == missing


@pytest.fixture
def runtime(store):
    name = "qa_runtime_" + uuid4().hex[:10]; password = secrets.token_urlsafe(32)
    with store.transaction() as cur:
        cur.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Identifier(name)), (password,))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(name)))
        cur.execute(sql.SQL(f"GRANT SELECT,INSERT,UPDATE ON {store.records} TO {{}}").format(sql.Identifier(name)))
        cur.execute(sql.SQL(f"GRANT SELECT,INSERT ON {store.versions} TO {{}}").format(sql.Identifier(name)))
    base = store.config
    class Config:
        settings_path, env_path = base.settings_path, base.env_path
        def __getattr__(self, key):
            return getattr(base, key)
        def env(self, key, default=""):
            return {"POSTGRES_USER": name, "POSTGRES_PASSWORD": password, "WORKSPACE_PROFILE": "production",
                    "WORKSPACE_SCHEMA_MODE": "verify", "WORKSPACE_REQUIRE_AUTH": "true", "WORKSPACE_ACCESS_TOKEN": "w"*40,
                    "WORKSPACE_MCP_TOKEN": "", "WEB_RATE_LIMIT_PER_MINUTE": "120"}.get(key, base.env(key, default))
    value = RecordStore(store.prefix, Config())
    try: yield value, name
    finally:
        with store.transaction() as cur:
            cur.execute(sql.SQL(f"REVOKE ALL PRIVILEGES ON {store.records},{store.versions} FROM {{}}").format(sql.Identifier(name)))
            cur.execute(sql.SQL("REVOKE ALL PRIVILEGES ON SCHEMA public FROM {}").format(sql.Identifier(name)))
            cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


def test_restricted_production_account_starts_and_crud_without_ddl(store, runtime, tmp_path, monkeypatch):
    restricted, _ = runtime
    assert restricted.verify_schema(require_runtime_role=True)["runtime_role_checked"]
    unchanged = state(store); restricted.ensure_schema(); assert state(store) == unchanged
    monkeypatch.setattr(ConfigLoader, "load_default", lambda: restricted.config)
    with TestClient(create_app(restricted, tmp_path, token="w"*40)) as client:
        header = {"Authorization": "Bearer " + "w"*40}
        made = client.post('/api/knowledge', headers=header, json={"data": {"title": "runtime", "content": "first"}})
        assert made.status_code == 201, made.text
        row = made.json()
        updated = client.put('/api/knowledge/'+row["id"], headers=header, json={"version": row["version"], "data": {"title": "runtime", "content": "second"}})
        assert updated.status_code == 200, updated.text
        listing = client.get('/api/knowledge', headers=header)
        assert listing.status_code == 200 and any(item["id"] == row["id"] for item in listing.json())
        history = client.get('/api/records/'+row["id"]+'/history', headers=header)
        assert history.status_code == 200 and len(history.json()) == 2
        deleted = client.delete('/api/records/'+row["id"], params={"version": updated.json()["version"]}, headers=header)
        assert deleted.status_code == 200 and deleted.json()["deleted"] is True
        restored = client.post('/api/records/'+row["id"]+'/restore', headers=header,
                               json={"target_version": row["version"], "current_version": deleted.json()["version"]})
        assert restored.status_code == 200 and restored.json()["data"]["content"] == "first", restored.text
        assert client.get('/health/ready').status_code == 200
    before = state(store)
    for statement in [f"CREATE TABLE {store.prefix}_forbidden(id int)", f"ALTER TABLE {store.records} ADD COLUMN forbidden text",
                      f"DROP TABLE {store.versions}", f"DELETE FROM {store.versions}", f"TRUNCATE {store.versions}",
                      f"UPDATE {store.versions} SET data=data"]:
        with pytest.raises(StorageError) as denied, restricted.transaction() as cur: cur.execute(statement)
        assert denied.value.__cause__.pgcode == "42501"
        assert state(store) == before
    history = restricted.history(row["id"])
    assert len(history) == 4
    versions = {item["version"]: item for item in history}
    assert versions[1]["data"]["content"] == "first" and versions[2]["data"]["content"] == "second"
    assert versions[3]["deleted"] is True and versions[4]["action"] == "restore:v1"


@pytest.mark.parametrize("privilege", ["UPDATE", "UPDATE(data)"])
def test_runtime_cannot_rewrite_history_through_table_or_column_grants(store, runtime, privilege):
    restricted, role = runtime
    before = state(store)
    assert restricted.verify_schema(require_runtime_role=True)["runtime_role_checked"]
    with store.transaction() as cur:
        cur.execute(sql.SQL(f"GRANT {privilege} ON {store.versions} TO {{}}").format(sql.Identifier(role)))
    try:
        with pytest.raises(StorageError, match="非必要的历史UPDATE"):
            restricted.verify_schema(require_runtime_role=True)
        assert state(store) == before
    finally:
        with store.transaction() as cur:
            cur.execute(sql.SQL(f"REVOKE {privilege} ON {store.versions} FROM {{}}").format(sql.Identifier(role)))
    assert restricted.verify_schema(require_runtime_role=True)["runtime_role_checked"]


@pytest.mark.parametrize("history_update", [False, True])
def test_minimum_history_privilege_catalog_contract(monkeypatch, history_update):
    """Pure catalog boundary only; real PostgreSQL cases above prove grant semantics."""
    layouts = []

    def layout(cur, name, expected, *, required_privileges):
        layouts.append((name, required_privileges))
        relation = {"oid": 1 if name == "records" else 2, "relnamespace": 3, "relowner": 4, "nspowner": 4}
        columns = {key: {"attnum": index} for index, key in enumerate(expected, 1)}
        constraints = [{"contype": "p"}]
        if name == "records":
            constraints.append({"contype": "c", "conname": "records_kind_check", "convalidated": True,
                                "expression": "(kind = ANY (ARRAY['knowledge'::text, 'plan'::text]))"})
        else:
            constraints.append({"contype": "f", "confrelid": 1, "convalidated": True, "conkey": [1],
                                "confkey": [1], "condeferrable": False, "confupdtype": "a", "confdeltype": "a"})
        return relation, columns, constraints

    class Cursor:
        def execute(self, query, args=()):
            if "FROM pg_roles WHERE rolname=current_user" in query:
                self.row = {"rolsuper": False, "rolcreatedb": False, "rolcreaterole": False,
                            "rolreplication": False, "rolbypassrls": False}
            elif "has_any_column_privilege" in query:
                assert args == (2,) and "'UPDATE'" in query
                self.row = {"allowed": history_update}
            elif " AS excessive" in query:
                self.row = {"excessive": False}
            elif " AS count" in query:
                self.row = {"count": 0}
            elif "has_database_privilege" in query or "has_table_privilege" in query:
                self.row = {"allowed": False}
            else:
                raise AssertionError("unexpected catalog query")

        def fetchone(self):
            return self.row

    monkeypatch.setattr(workspace_schema, "_layout", layout)
    if history_update:
        with pytest.raises(workspace_schema.SchemaValidationError, match="非必要的历史UPDATE"):
            workspace_schema.verify_workspace_schema(Cursor(), "records", "versions", {"knowledge", "plan"}, require_runtime_role=True)
    else:
        assert workspace_schema.verify_workspace_schema(Cursor(), "records", "versions", {"knowledge", "plan"}, require_runtime_role=True)["verified"]
    assert layouts == [("records", ("SELECT", "INSERT", "UPDATE")), ("versions", ("SELECT", "INSERT"))]


def test_excessive_or_missing_runtime_privileges_fail(store, runtime):
    restricted, role = runtime
    with pytest.raises(StorageError, match="权限过高"): store.verify_schema(require_runtime_role=True)
    with store.transaction() as cur: cur.execute(sql.SQL(f"GRANT DELETE ON {store.records} TO {{}}").format(sql.Identifier(role)))
    with pytest.raises(StorageError, match="非必要"): restricted.verify_schema(require_runtime_role=True)
    with store.transaction() as cur:
        cur.execute(sql.SQL(f"REVOKE DELETE,UPDATE ON {store.records} FROM {{}}").format(sql.Identifier(role)))
    with pytest.raises(StorageError, match="权限不完整"): restricted.verify_schema(require_runtime_role=True)


def test_cli_identity_confirmation_and_readonly_default(store):
    row = store.save("knowledge", {"title": "CLI preserved", "content": "owned fixture"})
    script = str(ROOT / "scripts/workspace_schema.py")
    command = [sys.executable, script, "--prefix", store.prefix, "--expected-database", "regression"]
    before = state(store)
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0 and json.loads(result.stdout)["ddl_executed"] is False
    result = subprocess.run(command[:-1]+["wrong-database"], capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 1
    result = subprocess.run([sys.executable, script, "migrate", "--prefix", store.prefix, "--expected-database", "regression"], capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 1 and state(store) == before
    replace_check(store, "kind IN ('knowledge','plan')")
    result = subprocess.run([sys.executable, script, "migrate", "--prefix", store.prefix, "--expected-database", "regression",
                             "--confirm", "仅创建或升级工作台结构，不删除记录"], capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0 and json.loads(result.stdout)["records_deleted"] == 0
    assert store.get(row["id"])["data"] == row["data"] and len(store.history(row["id"])) == 1
