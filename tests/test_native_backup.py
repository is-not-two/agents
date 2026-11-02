"""Local boundary tests plus mandatory owned-QA native pg_dump/pg_restore integration."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from contextlib import contextmanager
from io import BufferedReader, BytesIO
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "qa_backup"


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location(
        "native_backup_tests", ROOT / "scripts/database_backup.py"
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def catalog(module, database="source", empty=False):
    value = {
        "database": database,
        "role": "fixture",
        "session_role": "fixture",
        "database_oid": "1" if database == "source" else "2",
        "server_version_num": 160015,
        "encoding": "UTF8",
        "collate": "C",
        "ctype": "C",
        "in_recovery": False,
        "server_address": "127.0.0.1",
        "server_port": 5432,
        "cluster_identifier": "fixture-cluster",
        "other_connections": 0,
        "other_objects": [],
        "extensions": [{"name": "vector", "version": "0.8.2", "schema": "public"}],
        "relations": [],
        "columns": [],
        "constraints": [],
    }
    if not empty:
        for suffix, columns in [
            ("records", module.RECORD_COLUMNS),
            ("versions", module.VERSION_COLUMNS),
        ]:
            name = PREFIX + "_" + suffix
            value["relations"].append({"schema": "public", "name": name, "kind": "r"})
            value["columns"] += [
                {"schema": "public", "relation": name, "name": key, "type": kind}
                for key, kind in columns.items()
            ]
            value["constraints"].append(
                {
                    "schema": "public",
                    "relation": name,
                    "type": "p",
                    "validated": True,
                    "definition": "PRIMARY KEY (id)"
                    if suffix == "records"
                    else "PRIMARY KEY (record_id, version)",
                }
            )
    return value


class FakeDatabase:
    def __init__(self, value):
        self.value, self.closed, self.sessions, self.queries = value, False, [], []

    def set_session(self, **kwargs):
        self.sessions.append(kwargs)

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query):
        self.queries.append(query)

    def fetchone(self):
        return {"snapshot": "00000003-0000001A-1", "locked": True}

    def close(self):
        self.closed = True


@pytest.fixture
def boundary(module, tmp_path, monkeypatch):
    source, target = FakeDatabase(catalog(module)), FakeDatabase(catalog(module, "target", True))
    monkeypatch.setattr(module, "_catalog", lambda db: copy.deepcopy(db.value))
    commands = []

    def runner(command, **kwargs):
        commands.append((command, kwargs))
        assert kwargs["timeout"] > 0 and kwargs["env"]["PGPASSWORD"] == "SYNTHETIC_SECRET"
        if "--version" in command:
            output = b"pg_dump (PostgreSQL) 16.15\n"
        elif "--list" in command:
            output = b"1; 3079 123 EXTENSION - vector\n2; 0 0 COMMENT - EXTENSION vector\n3; 1259 55 TABLE public qa_backup_records fixture\n4; 1259 56 TABLE public qa_backup_versions fixture\n"
        elif command[0] == "pg_dump":
            kwargs["stdout"].write(b"PGDMPsynthetic fixture")
            output = b""
        else:
            listing = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--use-list="))
            assert b"EXTENSION" not in Path(listing).read_bytes()
            target.value = catalog(module, "target")
            output = b""
        return subprocess.CompletedProcess(command, 0, output, b"")

    common = {
        "expected_role": "fixture",
        "expected_project": module.PROJECT,
        "prefix": PREFIX,
        "runner": runner,
    }
    options = lambda database: {
        "host": "127.0.0.1",
        "port": "55432",
        "dbname": database,
        "user": "fixture",
        "password": "SYNTHETIC_SECRET",
    }
    backup = {
        **common,
        "expected_database": "source",
        "connection": options("source"),
        "connect": lambda **kw: source,
    }
    restore = {
        **common,
        "expected_database": "target",
        "expected_source_database": "source",
        "expected_source_role": "fixture",
        "connection": options("target"),
        "connect": lambda **kw: target,
        "workdir": tmp_path,
    }
    return source, target, commands, backup, restore, tmp_path / "artifacts/原生.dump"


def test_native_backup_snapshot_artifacts_and_password_boundary(module, boundary):
    source, _, commands, backup, _, file = boundary
    result = module.native_backup(file, **backup)
    assert result["snapshot_consistent"] and source.closed
    assert source.sessions == [{"readonly": True, "isolation_level": "REPEATABLE READ"}]
    assert any("pg_export_snapshot" in query for query in source.queries)
    assert any("--snapshot=00000003-0000001A-1" in command for command, _ in commands)
    manifest = json.loads(module._paths(file)[2].read_text(encoding="utf-8"))
    assert manifest["source"]["database_oid"] == "1" and manifest["prefix"] == PREFIX
    assert module._paths(file)[1].read_bytes() == (result["sha256"] + "  原生.dump\n").encode(
        "utf-8"
    )
    assert "SYNTHETIC_SECRET" not in json.dumps(manifest)
    assert all("SYNTHETIC_SECRET" not in " ".join(command) for command, _ in commands)
    assert set(file.parent.iterdir()) == set(module._paths(file))


def test_backup_hash_never_reads_archive_as_one_allocation(module, boundary, monkeypatch):
    _, _, _, backup, _, file = boundary
    original = Path.read_bytes

    def guarded(path):
        assert path.suffix != ".tmp", "archive must be hashed in bounded chunks"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    assert module.native_backup(file, **backup)["bytes"] == len(b"PGDMPsynthetic fixture")


def test_hash_stream_uses_bounded_reads_and_copies_exactly(module):
    class BoundedSource(BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024
            return super().read(size)

    value = b"PGDMP" + b"bounded" * (350 * 1024)
    destination = BytesIO()
    digest, size = module._hash_stream(BoundedSource(value), destination)
    assert (digest, size) == (hashlib.sha256(value).hexdigest(), len(value))
    assert destination.getvalue() == value


def test_backup_pg_restore_inherits_os_offset_not_python_buffer(module, boundary, monkeypatch):
    """Catch read-ahead drift before publication, without requiring hardlink permission."""
    _, _, _, backup, _, file = boundary

    class CheckedArchive(Exception):
        pass

    def inspect(runner, pg_restore, archive, env, timeout, prefix):
        archive.seek(0)
        assert archive.tell() == os.lseek(archive.fileno(), 0, os.SEEK_CUR) == 0
        assert not isinstance(archive, BufferedReader)
        raise CheckedArchive

    monkeypatch.setattr(module, "_toc", inspect)
    with pytest.raises(CheckedArchive):
        module.native_backup(file, **backup)
    assert not list(file.parent.iterdir())


def test_restore_frozen_archive_has_no_read_ahead_buffer(module, boundary, monkeypatch):
    """Check the actual temporary archive creation before sidecar/DB/tool access."""
    _, _, _, _, restore, file = boundary

    class CheckedArchive(Exception):
        pass

    def inspect(file, archive, *args):
        archive.write(b"PGDMP" + b"x" * 16000)
        archive.seek(0)
        assert archive.read(5) == b"PGDMP"
        archive.seek(0)
        assert archive.tell() == os.lseek(archive.fileno(), 0, os.SEEK_CUR) == 0
        raise CheckedArchive

    monkeypatch.setattr(module, "_verified_archive", inspect)
    with pytest.raises(CheckedArchive):
        module.native_restore(file, **restore)


@pytest.mark.parametrize("character", ["\n", "\r", "\t", "\x7f"])
def test_backup_rejects_control_filename_before_tools(module, boundary, character):
    _, _, commands, backup, _, file = boundary
    with pytest.raises(module.NativeBackupError, match="文件名"):
        module.native_backup(file.with_name("invalid" + character + ".dump"), **backup)
    assert not commands and not file.parent.exists()


@pytest.mark.parametrize("role", [0, 1, 2])
def test_backup_rejects_all_existing_roles(module, boundary, role):
    _, _, _, backup, _, file = boundary
    file.parent.mkdir()
    target = module._paths(file)[role]
    target.write_bytes(b"EXISTING")
    with pytest.raises(module.NativeBackupError, match="拒绝覆盖"):
        module.native_backup(file, **backup)
    assert list(file.parent.iterdir()) == [target] and target.read_bytes() == b"EXISTING"


def test_publish_collision_keeps_existing_and_cleans_ours(module, boundary, monkeypatch):
    _, _, _, backup, _, file = boundary
    original = os.link

    def race(source, target):
        if Path(target) == module._paths(file)[2]:
            Path(target).write_bytes(b"OTHER")
        return original(source, target)

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(FileExistsError):
        module.native_backup(file, **backup)
    assert list(file.parent.iterdir()) == [module._paths(file)[2]]
    assert module._paths(file)[2].read_bytes() == b"OTHER"


@pytest.mark.parametrize("mode", ["exit", "timeout", "missing"])
def test_tool_failure_redacts_and_cleans_staging(module, boundary, mode):
    _, _, _, backup, _, file = boundary

    def fail(command, **kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 1, stderr=b"SYNTHETIC_SECRET")
        if mode == "missing":
            raise FileNotFoundError("SYNTHETIC_SECRET")
        return subprocess.CompletedProcess(command, 1, b"", b"SYNTHETIC_SECRET")

    with pytest.raises(module.NativeBackupError) as caught:
        module.native_backup(file, **{**backup, "runner": fail})
    assert "SYNTHETIC_SECRET" not in str(caught.value)
    assert list(file.parent.iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_database", "wrong"),
        ("expected_role", "wrong"),
        ("expected_project", "wrong"),
        ("prefix", "bad;SQL"),
        ("timeout", True),
        ("timeout", 0),
    ],
)
def test_explicit_identity_rejects_before_tools(module, boundary, field, value):
    _, _, commands, backup, _, file = boundary
    with pytest.raises(module.NativeBackupError):
        module.native_backup(file, **{**backup, field: value})
    assert not commands


@pytest.mark.parametrize("defect", ["database", "role", "session_role", "column", "primary_key"])
def test_source_catalog_is_not_just_a_label(module, defect):
    value = catalog(module)
    if defect in {"database", "role", "session_role"}:
        value[defect] = "different"
    elif defect == "column":
        value["columns"][0]["type"] = "integer"
    else:
        value["constraints"] = []
    with pytest.raises(module.NativeBackupError):
        module._source_matches(value, "source", "fixture", PREFIX)


def test_restore_default_is_readonly_preflight_and_apply_is_transactional(module, boundary):
    _, target, commands, backup, restore, file = boundary
    module.native_backup(file, **backup)
    commands.clear()
    assert module.native_restore(file, **restore)["applied"] is False
    assert not any(any(arg.startswith("--dbname=") for arg in cmd) for cmd, _ in commands)
    result = module.native_restore(file, **restore, apply=True)
    command = commands[-1][0]
    assert result["applied"] is True and target.closed
    assert {"--single-transaction", "--exit-on-error", "--no-owner", "--no-privileges"} <= set(
        command
    )
    assert not any("--clean" in arg or "--create" in arg for arg in command)


@pytest.mark.parametrize("role", [0, 1, 2])
def test_restore_rejects_tampered_artifacts_before_connect(module, boundary, role):
    _, _, commands, backup, restore, file = boundary
    module.native_backup(file, **backup)
    commands.clear()
    path = module._paths(file)[role]
    path.write_bytes(path.read_bytes() + b"TAMPER")
    with pytest.raises(module.NativeBackupError):
        module.native_restore(file, **restore, apply=True)
    assert commands == []


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "nested_duplicate",
        "list",
        "boolean_schema",
        "boolean_size",
        "manifest_length",
        "sha_length",
    ],
)
def test_restore_rejects_malformed_or_oversized_sidecars_before_tools(module, boundary, defect):
    _, _, commands, backup, restore, file = boundary
    module.native_backup(file, **backup)
    commands.clear()
    sha, manifest = module._paths(file)[1:]
    text = manifest.read_text(encoding="utf-8")
    if defect == "duplicate":
        manifest.write_text('{"schema": 999,' + text[1:], encoding="utf-8")
    elif defect == "nested_duplicate":
        manifest.write_text(
            text.replace('"database": "source"', '"database": "wrong", "database": "source"'),
            encoding="utf-8",
        )
    elif defect == "list":
        manifest.write_text("[]", encoding="utf-8")
    elif defect == "boolean_schema":
        manifest.write_text(text.replace('"schema": 1', '"schema": true'), encoding="utf-8")
    elif defect == "boolean_size":
        value = json.loads(text)
        value["bytes"] = True
        manifest.write_text(json.dumps(value), encoding="utf-8")
    elif defect == "manifest_length":
        manifest.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    else:
        sha.write_bytes(sha.read_bytes() + b" " * (1024 * 1024))
    with pytest.raises(module.NativeBackupError):
        module.native_restore(file, **restore, apply=True)
    assert not commands


def test_sidecar_reads_are_bounded_even_when_file_grows(module, tmp_path, monkeypatch):
    reads = []

    class GrowingFile(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: GrowingFile(b"x" * 100))
    with pytest.raises(module.NativeBackupError):
        module._bounded_read(tmp_path / "fixture.sha256", 10)
    assert reads == [11]


@pytest.mark.parametrize("failure", ["catalog", "schema"])
def test_post_restore_failure_reports_committed_not_rollback(
    module, boundary, monkeypatch, failure
):
    _, target, _, backup, restore, file = boundary
    module.native_backup(file, **backup)
    original = restore["runner"]

    def restore_then_fail(command, **kwargs):
        result = original(command, **kwargs)
        if any(argument.startswith("--dbname=") for argument in command):
            if failure == "catalog":

                def unavailable(db):
                    raise psycopg2.OperationalError("SYNTHETIC_SECRET")

                monkeypatch.setattr(module, "_catalog", unavailable)
            else:
                target.value["constraints"] = []
        return result

    with pytest.raises(module.NativeRestoreCommittedError, match="已成功提交") as caught:
        module.native_restore(file, **{**restore, "runner": restore_then_fail}, apply=True)
    assert "未自动回滚" in str(caught.value) and "SYNTHETIC_SECRET" not in str(caught.value)
    assert target.closed


def test_cli_post_restore_failure_is_distinct_exit_two(module, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "database_backup.py",
            "restore",
            "--file",
            "fixture.dump",
            "--expected-database",
            "target",
            "--expected-role",
            "fixture",
            "--expected-source-database",
            "source",
            "--expected-source-role",
            "fixture",
            "--expected-project",
            module.PROJECT,
            "--prefix",
            PREFIX,
            "--apply",
        ],
    )

    def committed(*args, **kwargs):
        raise module.NativeRestoreCommittedError("SYNTHETIC_SECRET")

    monkeypatch.setattr(module, "native_restore", committed)
    assert module.main() == 2
    output = capsys.readouterr()
    assert not output.out and "NATIVE_RESTORE_COMMITTED_UNVERIFIED" in output.err
    assert "SYNTHETIC_SECRET" not in output.err


@pytest.mark.parametrize(
    "defect",
    [
        "same_name",
        "same_oid",
        "table",
        "function",
        "connections",
        "recovery",
        "version",
        "locale",
        "vector_missing",
        "vector_version",
        "role",
    ],
)
def test_restore_target_must_be_independent_empty_compatible(module, defect):
    source = catalog(module)
    target = catalog(module, "target", True)
    manifest = {"source": source, "pg_dump_major": 16}
    database = "target"
    if defect == "same_name":
        target["database"] = database = "source"
    elif defect == "same_oid":
        target["database_oid"] = source["database_oid"]
    elif defect == "table":
        target["relations"] = [{"name": "existing"}]
    elif defect == "function":
        target["other_objects"] = [{"kind": "function"}]
    elif defect == "connections":
        target["other_connections"] = 1
    elif defect == "recovery":
        target["in_recovery"] = True
    elif defect == "version":
        target["server_version_num"] = 170000
    elif defect == "locale":
        target["collate"] = "different"
    elif defect == "vector_missing":
        target["extensions"] = []
    elif defect == "vector_version":
        target["extensions"][0]["version"] = "different"
    else:
        target["role"] = "different"
    with pytest.raises(module.NativeBackupError):
        module._empty_target(target, manifest, database, "fixture")


def test_restore_uses_frozen_verified_bytes(module, boundary, monkeypatch):
    _, _, _, backup, restore, file = boundary
    module.native_backup(file, **backup)
    runner = restore["runner"]

    def swap(command, **kwargs):
        if "--list" in command:
            file.write_bytes(b"UNTRUSTED REPLACEMENT")
        if any(arg.startswith("--dbname=") for arg in command):
            assert kwargs["stdin"].read() == b"PGDMPsynthetic fixture"
            kwargs["stdin"].seek(0)
        return runner(command, **kwargs)

    assert module.native_restore(file, **{**restore, "runner": swap}, apply=True)["applied"]


def test_cli_missing_source_identity_redacts(module, monkeypatch, capsys):
    monkeypatch.setenv("POSTGRES_PASSWORD", "SYNTHETIC_SECRET")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "database_backup.py",
            "restore",
            "--file",
            "fixture.dump",
            "--expected-database",
            "target",
            "--expected-role",
            "fixture",
            "--expected-project",
            module.PROJECT,
            "--prefix",
            PREFIX,
        ],
    )
    assert module.main() == 1
    output = capsys.readouterr()
    assert not output.out and "SYNTHETIC_SECRET" not in output.err


@pytest.fixture
def owned_databases(tmp_path):
    """Never silently skip integration: coordinator must supply its owned QA env."""
    run_id = os.environ.get("SHILIE_QA_RUN_ID", "")
    assert re.fullmatch("[a-f0-9]{12}", run_id), (
        "integration requires owned ci_verify QA environment"
    )
    assert os.environ.get("POSTGRES_DB") == os.environ.get("POSTGRES_USER") == "regression"
    port = os.environ.get("POSTGRES_PORT", "")
    assert os.environ.get("POSTGRES_HOST") == "127.0.0.1"
    assert port.isdigit() and 1 <= int(port) <= 65535 and port != "5432"
    native_bin = os.environ.get("SHILIE_QA_NATIVE_BIN", "")
    docker, native = None, None
    container = "shilie-qa-" + run_id
    if native_bin:
        spec = importlib.util.spec_from_file_location(
            "native_qa_fixture", ROOT / "scripts/native_qa.py"
        )
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
    else:
        docker = shutil.which("docker")
        assert docker, "owned QA needs the native cluster coordinator or Docker CLI"

    def check_label():
        if native is not None:
            # Marker SHA, UID, live PID, installed binary hashes, actual SQL
            # data_directory/cluster_name/token/localhost endpoint: never env alone.
            native.verify_owned_cluster()
            return
        check = subprocess.run(
            [
                docker,
                "inspect",
                "--format",
                "{{json .Config.Labels}}\n{{json .NetworkSettings.Ports}}\n{{.State.Running}}",
                container,
            ],
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert check.returncode == 0, "owned QA container inspection failed"
        lines = check.stdout.decode("utf-8").splitlines()
        assert len(lines) == 3
        assert json.loads(lines[0]).get("io.shilie.regression") == run_id
        assert json.loads(lines[1]).get("5432/tcp") == [{"HostIp": "127.0.0.1", "HostPort": port}]
        assert lines[2] == "true"

    check_label()
    base = {
        "host": "127.0.0.1",
        "port": os.environ["POSTGRES_PORT"],
        "user": "regression",
        "password": os.environ["POSTGRES_PASSWORD"],
    }
    stem = "qa_backup_" + run_id + "_" + uuid4().hex
    names = {kind: stem + "_" + kind for kind in ("source", "target", "denied")}
    role, password = stem + "_role", secrets.token_urlsafe(24)
    admin = psycopg2.connect(**base, dbname="regression")
    admin.autocommit = True
    created_names, created_role = [], False
    failures = []

    def options(kind, restricted=False):
        return {
            **base,
            "dbname": names[kind],
            **({"user": role, "password": password} if restricted else {}),
        }

    @contextmanager
    def connect(kind, restricted=False):
        db = psycopg2.connect(**options(kind, restricted))
        try:
            with db:
                yield db
        finally:
            db.close()

    try:
        with admin.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s"
                ).format(sql.Identifier(role)),
                (password,),
            )
            created_role = True
            for name in names.values():
                cur.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
                )
                created_names.append(name)
        for kind in names:
            with connect(kind) as db, db.cursor() as cur:
                cur.execute("CREATE EXTENSION vector")
                if kind == "denied":
                    cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                    cur.execute(
                        sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier(role))
                    )
                    cur.execute(
                        sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(role))
                    )
        from rag_tech_retriever.platform.record_store import RECORD_KINDS

        with connect("source") as db, db.cursor() as cur:
            allowed = sql.SQL(",").join(sql.Literal(kind) for kind in sorted(RECORD_KINDS))
            cur.execute(
                sql.SQL(
                    "CREATE TABLE qa_backup_records(id TEXT PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ({})),version INTEGER NOT NULL,data JSONB NOT NULL,deleted BOOLEAN NOT NULL DEFAULT FALSE,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
                ).format(allowed)
            )
            cur.execute(
                "CREATE TABLE qa_backup_versions(record_id TEXT NOT NULL REFERENCES qa_backup_records(id),version INTEGER NOT NULL,data JSONB NOT NULL,deleted BOOLEAN NOT NULL,action TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(record_id,version))"
            )
            cur.execute(
                'INSERT INTO qa_backup_records(id,kind,version,data) VALUES (\'owned\',\'knowledge\',1,\'{"title":"fixture","content":"first"}\')'
            )
            cur.execute(
                "INSERT INTO qa_backup_versions SELECT id,version,data,deleted,'create',created_at FROM qa_backup_records"
            )
            cur.execute(
                'UPDATE qa_backup_records SET version=2,data=\'{"title":"fixture","content":"second"}\''
            )
            cur.execute(
                "INSERT INTO qa_backup_versions SELECT id,version,data,deleted,'update',updated_at FROM qa_backup_records"
            )
            cur.execute(
                "CREATE TABLE qa_backup_vectors(id INTEGER PRIMARY KEY,embedding vector(4) NOT NULL,CONSTRAINT qa_backup_admin_load CHECK(current_user='regression'))"
            )
            cur.execute("INSERT INTO qa_backup_vectors VALUES (1,'[1,0,0,0]'),(2,'[0,1,0,0]')")
            cur.execute("COMMENT ON TABLE qa_backup_vectors IS 'owned QA metadata'")

        def adapter(command, **kwargs):
            check_label()
            translated, remote = list(command), None
            try:
                if native is not None:
                    assert command[0] in ("pg_dump", "pg_restore")
                    assert kwargs["env"]["PGHOST"] == "127.0.0.1"
                    assert kwargs["env"]["PGPORT"] == port
                    assert kwargs["env"]["PGDATABASE"] in names.values()
                    assert kwargs["env"]["PGUSER"] in ("regression", role)
                    translated[0] = str(Path(native_bin) / command[0])
                for index, argument in enumerate(translated):
                    if native is None and argument.startswith("--use-list="):
                        remote = "/tmp/qa-native-" + run_id + "-" + uuid4().hex + ".list"
                        cp = subprocess.run(
                            [docker, "cp", argument.split("=", 1)[1], container + ":" + remote],
                            capture_output=True,
                            check=False,
                            timeout=10,
                        )
                        assert cp.returncode == 0
                        translated[index] = "--use-list=" + remote
                flags = ["--env", "PGHOST=127.0.0.1", "--env", "PGPORT=5432"]
                for key in ("PGDATABASE", "PGUSER", "PGPASSWORD", "PGOPTIONS", "PGCONNECT_TIMEOUT"):
                    flags += ["--env", key]
                assert kwargs.pop("check") is False
                check_label()
                stdin = kwargs.get("stdin")
                logical = stdin.tell() if stdin is not None else None
                physical = os.lseek(stdin.fileno(), 0, os.SEEK_CUR) if stdin is not None else None
                result = subprocess.run(
                    translated
                    if native is not None
                    else [docker, "exec", "-i", *flags, container, *translated],
                    check=False,
                    **kwargs,
                )
                if result.returncode:
                    # Only this label/port-verified synthetic fixture reaches here.
                    # Preserve the real CLI cause, not environment/command/credentials.
                    excerpt = result.stderr[:4096].decode("utf-8", "replace")
                    for value in (base["password"], password, *names.values(), role):
                        excerpt = excerpt.replace(value, "<OWNED_QA_REDACTED>")
                    diagnostic = {
                        "tool": command[0],
                        "phase": "list" if "--list" in command else "restore",
                        "exit": result.returncode,
                        "stderr_excerpt": excerpt,
                        "stdin_logical_offset": logical,
                        "stdin_os_offset": physical,
                        "legacy_buffered_stdin_probe": isinstance(stdin, BufferedReader),
                    }
                    external = os.environ.get("SHILIE_QA_OUTPUT")
                    audit = (
                        Path(external) / "backup-audit"
                        if external
                        else ROOT / "output/product-20261028/release-b/backup-audit"
                    )
                    audit.mkdir(parents=True, exist_ok=True)
                    with (audit / ("owned-pgcli-" + run_id + ".jsonl")).open(
                        "a", encoding="utf-8"
                    ) as log:
                        log.write(json.dumps(diagnostic, ensure_ascii=False) + "\n")
                    print("NATIVE_PGCLI_DIAGNOSTIC " + json.dumps(diagnostic, ensure_ascii=False))
                if "--dbname=" + names["denied"] in command and result.returncode:
                    assert b"qa_backup_admin_load" in result.stderr, (
                        "expected late fixture CHECK failure"
                    )
                    failures.append("fixture_data_constraint")
                return result
            finally:
                if remote:
                    check_label()
                    subprocess.run(
                        [docker, "exec", container, "rm", "-f", "--", remote],
                        capture_output=True,
                        check=False,
                        timeout=10,
                    )

        yield {
            "names": names,
            "role": role,
            "options": options,
            "connect": connect,
            "runner": adapter,
            "failures": failures,
            "workdir": tmp_path,
        }
    finally:
        try:
            check_label()
            with admin.cursor() as cur:
                for name in created_names:
                    assert name.startswith(stem + "_")
                    cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
                if created_role:
                    cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        finally:
            admin.close()


def state(fixture, kind):
    """Digest exact synthetic rows, vectors and constraints without printing values."""
    result = {}
    with fixture["connect"](kind) as db, db.cursor() as cur:
        for name in ("records", "versions", "vectors"):
            cur.execute(
                "SELECT row_to_json(t)::text FROM qa_backup_"
                + name
                + " t ORDER BY row_to_json(t)::text"
            )
            rows = cur.fetchall()
            result[name] = {
                "rows": len(rows),
                "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
            }
        cur.execute(
            "SELECT c.relname,con.conname,pg_get_constraintdef(con.oid) FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY 1,2"
        )
        result["constraints_sha256"] = hashlib.sha256(
            json.dumps(cur.fetchall()).encode()
        ).hexdigest()
        cur.execute("SELECT obj_description('qa_backup_vectors'::regclass,'pg_class')")
        result["metadata_sha256"] = hashlib.sha256(json.dumps(cur.fetchone()).encode()).hexdigest()
    return result


def test_integration_native_backup_restore_and_transaction_failure(module, owned_databases):
    fixture = owned_databases
    names = fixture["names"]
    file = fixture["workdir"] / "真实原生.dump"
    common = {
        "expected_project": module.PROJECT,
        "prefix": PREFIX,
        "runner": fixture["runner"],
        "timeout": 60,
    }
    before = state(fixture, "source")
    module.native_backup(
        file,
        expected_database=names["source"],
        expected_role="regression",
        connection=fixture["options"]("source"),
        **common,
    )
    # Reproduce QA02's exact inherited-handle bug using read-only pg_restore --list.
    # The real tool stderr is retained by the owned-only adapter, without secrets.
    with file.open("rb") as buffered:
        assert buffered.read(5) == b"PGDMP"
        buffered.seek(0)
        assert buffered.tell() == 0 and os.lseek(buffered.fileno(), 0, os.SEEK_CUR) > 0
        options = module._options(fixture["options"]("source"), names["source"], "regression", 60)
        legacy = fixture["runner"](
            ["pg_restore", "--list"],
            env=module._environment(options, 60),
            timeout=60,
            check=False,
            stdin=buffered,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert legacy.returncode != 0, (
            "legacy buffered stdin must not masquerade as a valid archive"
        )
    restore = {
        **common,
        "expected_source_database": names["source"],
        "expected_source_role": "regression",
        "expected_role": "regression",
        "workdir": fixture["workdir"],
    }
    assert (
        module.native_restore(
            file,
            expected_database=names["target"],
            connection=fixture["options"]("target"),
            **restore,
        )["applied"]
        is False
    )
    assert module.native_restore(
        file,
        expected_database=names["target"],
        connection=fixture["options"]("target"),
        apply=True,
        **restore,
    )["applied"]
    restored = state(fixture, "target")
    assert restored == before
    with pytest.raises(module.NativeBackupError):
        module.native_restore(
            file,
            expected_database=names["target"],
            connection=fixture["options"]("target"),
            apply=True,
            **restore,
        )
    with pytest.raises(module.NativeBackupError):
        module.native_restore(
            file,
            expected_database=names["denied"],
            connection=fixture["options"]("denied", True),
            apply=True,
            **{**restore, "expected_role": fixture["role"]},
        )
    with fixture["connect"]("denied") as db, db.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
        assert cur.fetchone()[0] == 0
    assert fixture["failures"] == ["fixture_data_constraint"]
    after = state(fixture, "source")
    assert after == before

    def fingerprint(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    print(
        "NATIVE_BACKUP_PROOF "
        + json.dumps(
            {
                "records": before["records"],
                "history": before["versions"],
                "vectors": before["vectors"],
                "constraints_sha256": before["constraints_sha256"],
                "metadata_sha256": before["metadata_sha256"],
                "source_unchanged": True,
                "source_sha256_before": fingerprint(before),
                "source_sha256_after": fingerprint(after),
                "restored_sha256": fingerprint(restored),
                "restored_equal": True,
                "nonempty_target_denied": True,
                "denied_restore_transaction_empty": True,
                "denied_restore_late_check_failure": True,
                "legacy_buffered_stdin_reproduced": True,
            },
            sort_keys=True,
        )
    )
