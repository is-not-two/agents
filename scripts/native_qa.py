"""Linux non-root QA: own a fresh PostgreSQL 16 cluster; never use an existing DB.

Root provisions the dedicated OS account, Python dependencies and pgvector first.
Run this account in a private network namespace (e.g. systemd PrivateNetwork=yes)
with production data/config/socket paths inaccessible. This script is not an OS
sandbox for arbitrary tests and cannot itself prevent connections to host :5432.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import closing
from pathlib import Path

import psycopg2

PG_BIN = Path("/usr/lib/postgresql/16/bin")
TOOLS = ("initdb", "pg_ctl", "postgres", "pg_dump", "pg_restore")


class NativeQAError(ValueError):
    """Fail closed without printing credentials or an inherited environment."""


def _failure_event(phase: str, error: Exception) -> dict:
    """Emit fixed categories only: never stringify database, OS or credential errors."""
    if isinstance(error, NativeQAError):
        code = "OWNED_QA_VALIDATION_FAILED"
    elif isinstance(error, psycopg2.Error):
        code = "OWNED_QA_DATABASE_FAILED"
    elif isinstance(error, OSError):
        code = "OWNED_QA_OS_OPERATION_FAILED"
    else:
        code = "OWNED_QA_STATE_FORMAT_INVALID"
    event = {"event": "NATIVE_QA_PHASE_FAILED", "phase": phase, "reason_code": code}
    print(json.dumps(event), flush=True)
    return event


def digest(path: Path) -> str:
    """Hash a file with bounded memory."""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _prepare_workspace(source: Path, root: Path) -> dict:
    """Copy only static configuration/fixtures; never .env or user/runtime data."""
    if root.resolve(strict=True) != root:
        raise NativeQAError("QA cluster root is not resolved")
    _owned(root, os.geteuid(), directory=True)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    if workspace.resolve(strict=True).parent != root:
        raise NativeQAError("QA workspace escaped owned cluster root")
    _owned(workspace, os.geteuid(), directory=True)
    (workspace / "config").mkdir(mode=0o700)
    (workspace / "data/processed").mkdir(mode=0o700, parents=True)
    (workspace / "data/raw/aihuoke_docs").mkdir(mode=0o700, parents=True)
    files = sorted((source / "config").iterdir())
    fixtures = (
        "corpus.jsonl",
        "agent_golden_set.json",
        "collaboration_tasks.json",
        "eval_questions.json",
    )
    files.extend(source / "data/processed" / name for name in fixtures)
    optional = source / "data/processed/eval_questions_python_docs.json"
    if optional.exists():
        files.append(optional)
    manifest = {}
    for original in files:
        relative = original.relative_to(source)
        if (
            original.is_symlink()
            or not original.is_file()
            or not original.resolve(strict=True).is_relative_to(source)
            or original.name.startswith(".")
            or (relative.parts[0] == "config" and original.suffix not in (".yaml", ".yml", ".json"))
        ):
            raise NativeQAError("QA workspace accepts static regular config/fixture files only")
        copied = workspace / relative
        expected = digest(original)
        shutil.copyfile(original, copied)
        copied.chmod(0o400)
        if digest(copied) != expected or digest(original) != expected:
            raise NativeQAError("QA workspace static copy SHA mismatch")
        manifest[relative.as_posix()] = {"sha256": expected, "bytes": copied.stat().st_size}
    return {
        "source": str(source),
        "cluster_root": str(root),
        "workspace": str(workspace),
        "files": manifest,
    }


def _verify_workspace(proof: dict) -> None:
    """Assert the same owned workspace and unchanged read-only copied fixtures."""
    root, workspace, source = (Path(proof[key]) for key in ("cluster_root", "workspace", "source"))
    if workspace != root / "workspace" or workspace.resolve(strict=True).parent != root:
        raise NativeQAError("QA workspace identity changed")
    _owned(root, os.geteuid(), directory=True)
    _owned(workspace, os.geteuid(), directory=True)
    if (workspace / ".env").exists():
        raise NativeQAError("QA workspace must not acquire an environment credential file")
    for relative, value in proof["files"].items():
        copied, original = workspace / relative, source / relative
        if (
            copied.is_symlink()
            or not copied.is_file()
            or copied.stat().st_mode & 0o222
            or digest(copied) != value["sha256"]
            or digest(original) != value["sha256"]
        ):
            raise NativeQAError("QA static source/workspace fixtures changed")


def _linux_user(expected: str | None = None) -> int:
    if sys.platform != "linux" or os.geteuid() == 0 or os.getuid() != os.geteuid():
        raise NativeQAError("Linux dedicated non-root account required")
    import pwd

    uid = os.geteuid()
    if expected and pwd.getpwuid(uid).pw_name != expected:
        raise NativeQAError("Dedicated QA OS account mismatch")
    status = Path("/proc/self/status").read_text(encoding="ascii")
    if not re.search(r"^CapEff:\s+0+$", status, re.MULTILINE):
        raise NativeQAError("QA account must have no effective capabilities")
    return uid


def _owned(path: Path, uid: int, *, directory: bool = False) -> None:
    info = path.lstat()
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid or info.st_uid != uid or info.st_mode & 0o077:
        raise NativeQAError("QA path ownership/mode mismatch")


def binaries(directory: Path) -> dict[str, str]:
    """Accept only installed, root-owned, non-group/world-writable PG16 tools."""
    if directory != PG_BIN or directory.resolve(strict=True) != PG_BIN:
        raise NativeQAError("Only the provisioned PostgreSQL 16 binary directory is allowed")
    for parent in (directory, *directory.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise NativeQAError("Untrusted PostgreSQL binary directory")
    values = {}
    for name in TOOLS:
        path = directory / name
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o022
            or not os.access(path, os.X_OK)
        ):
            raise NativeQAError("Untrusted PostgreSQL binary")
        values[name] = digest(path)
    return values


def _marker(env: dict, *, allow_uninitialized: bool = False) -> tuple[Path, dict]:
    uid = _linux_user()
    run = env.get("SHILIE_QA_RUN_ID", "")
    if not re.fullmatch(r"[a-f0-9]{12}", run):
        raise NativeQAError("Owned QA run identity required")
    root = Path(env["SHILIE_QA_NATIVE_ROOT"])
    marker = root / "owner.json"
    if (
        not root.is_absolute()
        or root.resolve(strict=True) != root
        or not root.name.startswith("shilie-native-qa-")
    ):
        raise NativeQAError("Invalid owned cluster root")
    _owned(root, uid, directory=True)
    _owned(marker, uid)
    if marker.stat().st_size > 8192:
        raise NativeQAError("Invalid QA ownership marker")
    raw = marker.read_bytes()
    if not hmac.compare_digest(
        hashlib.sha256(raw).hexdigest(), env["SHILIE_QA_NATIVE_MARKER_SHA256"]
    ):
        raise NativeQAError("QA marker SHA mismatch")
    value = json.loads(raw)
    token_sha = hashlib.sha256(env["SHILIE_QA_NATIVE_TOKEN"].encode()).hexdigest()
    if (
        value.get("uid") != uid
        or value.get("run_id") != run
        or value.get("root") != str(root)
        or value.get("data_directory") != str(root / "data")
        or value.get("cluster_name") != "shilie_qa_" + run
        or not hmac.compare_digest(value.get("token_sha256", ""), token_sha)
        or value.get("bin") != env.get("SHILIE_QA_NATIVE_BIN")
        or env.get("POSTGRES_HOST") != "127.0.0.1"
        or str(value.get("port")) != env.get("POSTGRES_PORT")
        or not isinstance(value.get("port"), int)
        or not 1024 <= value["port"] <= 65535
        or value["port"] == 5432
    ):
        raise NativeQAError("QA marker/endpoint identity mismatch")
    data = root / "data"
    if allow_uninitialized and not os.path.lexists(data):
        if value.get("pid") is not None:
            raise NativeQAError("An initialized marker cannot lose its data directory")
    else:
        _owned(data, uid, directory=True)
    return root, value


def _pid(root: Path, marker: dict) -> int | None:
    path = root / "data/postmaster.pid"
    if not path.exists():
        return None
    _owned(path, marker["uid"])
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 4 or lines[1] != str(root / "data") or lines[3] != str(marker["port"]):
        raise NativeQAError("Postmaster PID file identity mismatch")
    pid = int(lines[0])
    proc = Path("/proc") / str(pid)
    if not proc.exists():
        raise NativeQAError("Stale PID file: retain cluster for manual inspection")
    command = (proc / "cmdline").read_bytes().split(b"\0")
    if (
        pid <= 1
        or proc.stat().st_uid != marker["uid"]
        or command[:3] != [str(PG_BIN / "postgres").encode(), b"-D", str(root / "data").encode()]
        or marker.get("pid") not in (None, pid)
    ):
        raise NativeQAError("Postmaster process does not belong to this run")
    return pid


def verify_owned_cluster(env: dict | None = None) -> dict:
    """Verify marker SHA/token, binaries, PID and actual SQL endpoint before writes."""
    env = dict(os.environ) if env is None else env
    root, value = _marker(env)
    if (
        binaries(Path(env["SHILIE_QA_NATIVE_BIN"])) != value["binaries"]
        or _pid(root, value) != value["pid"]
    ):
        raise NativeQAError("QA binary/PID identity mismatch")
    with (
        closing(
            psycopg2.connect(
                host="127.0.0.1",
                port=value["port"],
                dbname="regression",
                user="regression",
                password=env["POSTGRES_PASSWORD"],
                connect_timeout=3,
                options="-c statement_timeout=3000 -c default_transaction_read_only=on",
            )
        ) as db,
        db.cursor() as cur,
    ):
        cur.execute(
            "SELECT current_database(),current_user,current_setting('data_directory'),current_setting('cluster_name'),current_setting('shilie.qa_token_sha256'),host(inet_server_addr()),inet_server_port(),current_setting('server_version_num')::int"
        )
        observed = cur.fetchone()
    expected = (
        "regression",
        "regression",
        str(root / "data"),
        value["cluster_name"],
        value["token_sha256"],
        "127.0.0.1",
        value["port"],
    )
    if observed[:7] != expected or observed[7] // 10000 != 16:
        raise NativeQAError("Actual PostgreSQL cluster/endpoint proof mismatch")
    return {
        "run_id": value["run_id"],
        "uid": value["uid"],
        "pid": value["pid"],
        "root": str(root),
        "data_directory": str(root / "data"),
        "cluster_name": value["cluster_name"],
        "host": "127.0.0.1",
        "port": value["port"],
        "server_version_num": observed[7],
        "marker_sha256": env["SHILIE_QA_NATIVE_MARKER_SHA256"],
        "token_sha256": value["token_sha256"],
        "binaries": value["binaries"],
    }


def _write_marker(root: Path, value: dict, env: dict) -> None:
    path = root / "owner.json"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
    env["SHILIE_QA_NATIVE_MARKER_SHA256"] = digest(path)


def _command(
    command: list[str],
    *,
    env: dict,
    output: Path,
    label: str,
    password: str,
    timeout: int = 60,
    input_data: bytes | None = None,
) -> int:
    try:
        result = subprocess.run(
            command, env=env, input=input_data, capture_output=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired as error:
        result = subprocess.CompletedProcess(command, 124, error.stdout or b"", error.stderr or b"")
    for name, data in (("stdout", result.stdout), ("stderr", result.stderr)):
        text = data.decode("utf-8", "replace")
        for secret in (password, env.get("SHILIE_QA_NATIVE_TOKEN", "")):
            if secret:
                text = text.replace(secret, "<QA_SECRET_REDACTED>")
        (output / f"{label}.{name}.txt").write_text(text, encoding="utf-8")
    (output / f"{label}.exit.txt").write_text(str(result.returncode), encoding="ascii")
    return result.returncode


def _source_manifest(source: Path) -> dict:
    """Use the same exact source allowlist as the release gate and source package."""
    sys.path.insert(0, str(source / "src"))
    try:
        from rag_tech_retriever.common.release_manifest import source_manifest

        return source_manifest(source)
    finally:
        sys.path.pop(0)


def _pytest_proof(path: Path) -> dict:
    """Record every skip and require actual passing critical native integrations."""
    if path.stat().st_size > 16 * 1024 * 1024:
        raise NativeQAError("Oversized pytest proof")
    cases = []
    try:
        suite = ET.parse(path)
    except ET.ParseError as error:
        raise NativeQAError("Invalid pytest proof") from error
    for case in suite.iter("testcase"):
        failure, error, skipped = (case.find(key) for key in ("failure", "error", "skipped"))
        outcome = "failed" if failure is not None or error is not None else "skipped" if skipped is not None else "passed"
        value = {"name": case.get("name", ""), "class": case.get("classname", ""), "outcome": outcome}
        if skipped is not None:
            value["reason"] = skipped.get("message", "")
        cases.append(value)
    required = {
        "test_native_backup": {"test_integration_native_backup_restore_and_transaction_failure"},
        "test_native_release": {"test_native_release_actual_production_app_upgrade_and_recovery",
                                "test_native_release_stop_waits_for_os_exit_not_listener_loss"},
        "test_native_schema": {"test_restricted_production_account_starts_and_crud_without_ddl",
                               "test_valid_schema_verification_is_readonly_and_local_old_upgrade_preserves_history"},
    }
    critical = [item for item in cases if item["class"].rsplit(".", 1)[-1] in required]
    missing = [f"{module}::{name}" for module, names in required.items() for name in sorted(names)
               if not any(item["class"].rsplit(".", 1)[-1] == module and item["name"] == name
                          and item["outcome"] == "passed" for item in critical)]
    return {"cases": len(cases), "passed": sum(item["outcome"] == "passed" for item in cases),
            "failed": sum(item["outcome"] == "failed" for item in cases),
            "skipped": [item for item in cases if item["outcome"] == "skipped"],
            "critical_native": critical, "missing_critical_passes": missing,
            "critical_native_passed": not missing}


def run(source: Path, output: Path, work_root: Path, expected_user: str, timeout: int,
        *, gate_session: bool = False) -> dict:
    """Own one random cluster lifecycle; preserve evidence outside its cleanup root."""
    uid = _linux_user(expected_user)
    os.umask(0o077)
    hashes = binaries(PG_BIN)
    source, work_root = source.resolve(strict=True), work_root.resolve(strict=True)
    if (
        not (source / "pyproject.toml").is_file()
        or not (source / "scripts/seed_ci_corpus.py").is_file()
    ):
        raise NativeQAError("Explicit project source required")
    manifest = _source_manifest(source)
    output = output.absolute()
    if output.exists() or output.parent.resolve(strict=True) != output.parent:
        raise NativeQAError("Use a fresh output directory with a resolved parent")
    output.mkdir(mode=0o700)
    _owned(output, uid, directory=True)
    root = Path(tempfile.mkdtemp(prefix="shilie-native-qa-", dir=work_root)).resolve()
    root.chmod(0o700)
    run_id, password, token = (
        secrets.token_hex(6),
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(32),
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    if port == 5432:
        raise NativeQAError("Refusing standard PostgreSQL port")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PG", "POSTGRES_", "SHILIE_QA_"))
    }
    env.pop("PYTEST_ADDOPTS", None)
    env.update(
        {
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": str(port),
            "POSTGRES_DB": "regression",
            "POSTGRES_USER": "regression",
            "POSTGRES_PASSWORD": password,
            "SHILIE_QA_RUN_ID": run_id,
            "SHILIE_QA_NATIVE_BIN": str(PG_BIN),
            "SHILIE_QA_NATIVE_ROOT": str(root),
            "SHILIE_QA_NATIVE_TOKEN": token,
            "SHILIE_QA_OUTPUT": str(output),
            "TMPDIR": str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(source / "src"),
            "PROJECT_ROOT": str(root / "workspace"),
            "RAG_PROJECT_ROOT": str(root / "workspace"),
            "WORKSPACE_REQUIRE_AUTH": "false",
            "WORKSPACE_PROFILE": "local",
            "WORKSPACE_ACCESS_TOKEN": "",
            "WORKSPACE_SCHEMA_MODE": "",
            "WORKSPACE_MCP_TOKEN": "",
            "LLM_API_KEY": "",
            "WEB_RATE_LIMIT_PER_MINUTE": "120",
        }
    )
    value = {
        "schema": 1,
        "uid": uid,
        "run_id": run_id,
        "root": str(root),
        "data_directory": str(root / "data"),
        "cluster_name": "shilie_qa_" + run_id,
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "port": port,
        "bin": str(PG_BIN),
        "binaries": hashes,
        "pid": None,
    }
    _write_marker(root, value, env)
    result, cleanup = (
        {"run_id": run_id, "output": str(output), "cluster_root": str(root), "ok": False,
         "source_manifest": manifest,
         "source_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
         "gate_session_requested": gate_session, "gate_session_completed": False,
         "completed_scenario": False},
        False,
    )
    previous = Path.cwd()
    phase = "prepare_workspace"
    try:
        os.chdir(source)
        workspace_proof = _prepare_workspace(source, root)
        _verify_workspace(workspace_proof)
        (output / "workspace-proof.json").write_text(
            json.dumps(workspace_proof, indent=2), encoding="utf-8"
        )
        phase = "initdb"
        if _command(
            [
                str(PG_BIN / "initdb"),
                "-D",
                str(root / "data"),
                "-U",
                "regression",
                "--auth-local=scram-sha-256",
                "--auth-host=scram-sha-256",
                "--encoding=UTF8",
                "--locale=C.UTF-8",
                "--pwfile=/dev/stdin",
            ],
            env=env,
            output=output,
            label="initdb",
            password=password,
            input_data=(password + "\n").encode(),
        ):
            raise NativeQAError("Owned initdb failed; inspect redacted evidence")

        def quote(item: str) -> str:
            return "'" + item.replace("'", "''") + "'"

        phase = "configure_cluster"
        settings = {
            "listen_addresses": "127.0.0.1",
            "port": str(port),
            "unix_socket_directories": str(root),
            "unix_socket_permissions": "0700",
            "cluster_name": value["cluster_name"],
            "shilie.qa_token_sha256": value["token_sha256"],
            "shared_buffers": "32MB",
        }
        with (root / "data/postgresql.conf").open("a", encoding="utf-8") as stream:
            stream.write(
                "\n" + "\n".join(key + "=" + quote(item) for key, item in settings.items()) + "\n"
            )
        phase = "start_cluster"
        if _command(
            [
                str(PG_BIN / "pg_ctl"),
                "-D",
                str(root / "data"),
                "-l",
                str(root / "postgres.log"),
                "-w",
                "-t",
                "30",
                "start",
            ],
            env=env,
            output=output,
            label="start",
            password=password,
        ):
            raise NativeQAError("Owned PostgreSQL startup failed")
        phase = "pid_identity"
        value["pid"] = _pid(root, value)
        if value["pid"] is None:
            raise NativeQAError("Missing owned postmaster PID")
        _write_marker(root, value, env)
        # Authenticate the initial postgres database only after PID/path proof.
        phase = "bootstrap_sql"
        with closing(
            psycopg2.connect(
                host="127.0.0.1",
                port=port,
                dbname="postgres",
                user="regression",
                password=password,
                connect_timeout=3,
            )
        ) as db:
            db.autocommit = True
            with db.cursor() as cur:
                cur.execute(
                    "SELECT current_setting('data_directory'),current_setting('cluster_name'),current_setting('shilie.qa_token_sha256')"
                )
                if cur.fetchone() != (
                    str(root / "data"),
                    value["cluster_name"],
                    value["token_sha256"],
                ):
                    raise NativeQAError("Initial cluster SQL identity mismatch")
                cur.execute("CREATE DATABASE regression")
        phase = "cluster_identity"
        proof = verify_owned_cluster(env)
        phase = "extension_install"
        with (
            closing(
                psycopg2.connect(
                    host="127.0.0.1",
                    port=port,
                    dbname="regression",
                    user="regression",
                    password=password,
                    connect_timeout=3,
                )
            ) as db,
            db.cursor() as cur,
        ):
            cur.execute("CREATE EXTENSION vector VERSION '0.8.7'")
            cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
            if cur.fetchone() != ("0.8.7",):
                raise NativeQAError("Provisioned pgvector 0.8.7 required")
            db.commit()
        proof["pgvector_version"] = "0.8.7"
        (output / "ownership-proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
        (output / "ownership-marker.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
        phase = "seed"
        if _command(
            [sys.executable, str(source / "scripts/seed_ci_corpus.py"), run_id],
            env=env,
            output=output,
            label="seed",
            password=password,
        ):
            raise NativeQAError("Owned corpus fixture seed failed")
        phase = "pretest_identity"
        verify_owned_cluster(env)
        phase = "pytest"
        pytest = _command(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-s",
                "-ra",
                "--tb=short",
                "--junitxml",
                str(output / "pytest.junit.xml"),
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(root / "pytest-tmp"),
            ],
            env=env,
            output=output,
            label="pytest",
            password=password,
            timeout=timeout,
        )
        result["pytest_exit"] = pytest
        phase = "ruff"
        ruff = _command(
            [sys.executable, "-m", "ruff", "check", "--no-cache", "src", "scripts", "tests"],
            env=env,
            output=output,
            label="ruff",
            password=password,
            timeout=timeout,
        )
        result["ruff_exit"] = ruff
        phase = "pytest_proof"
        pytest_proof = _pytest_proof(output / "pytest.junit.xml")
        (output / "pytest-proof.json").write_text(json.dumps(pytest_proof, indent=2), encoding="utf-8")
        result["pytest_proof"] = pytest_proof
        phase = "workspace_unchanged"
        _verify_workspace(workspace_proof)
        (output / "workspace-verified.json").write_text(
            json.dumps(workspace_proof, indent=2), encoding="utf-8"
        )
        result.update(
            {
                "pytest_exit": pytest,
                "ruff_exit": ruff,
                "ok": pytest == ruff == 0,
                "workspace": workspace_proof["workspace"],
                "static_fixtures_unchanged": True,
            }
        )
        if gate_session and result["ok"]:
            phase = "full_server_checks"
            commands = [
                ("pip-check", [sys.executable, "-m", "pip", "check"]),
                ("static-version", [sys.executable, str(source / "scripts/check_static_version.py")]),
                ("agent-eval", [sys.executable, str(source / "scripts/agent_eval.py"), "--report", str(output / "agent-contract.json")]),
                ("collaboration-eval", [sys.executable, str(source / "scripts/collaboration_eval.py"), "--report", str(output / "collaboration-comparison.json")]),
            ]
            for label, command in commands:
                code = _command(command, env=env, output=output, label=label,
                                password=password, timeout=120)
                result[label.replace("-", "_") + "_exit"] = code
                if code:
                    raise NativeQAError("Full server check failed")
            if not pytest_proof["critical_native_passed"]:
                raise NativeQAError("Critical native integration was skipped or absent")
            phase = "gate_session"
            from native_gate_server import run_session

            def stop_database() -> dict:
                """Stop only the exact SQL/PID/marker-verified disposable cluster."""
                observed = verify_owned_cluster(env)
                code = _command([str(PG_BIN / "pg_ctl"), "-D", str(root / "data"),
                                 "-m", "fast", "-w", "-t", "30", "stop"],
                                env=env, output=output, label="gate-db-stop", password=password)
                if code or _pid(root, value) is not None:
                    raise NativeQAError("Owned database stop was not confirmed")
                value["pid"] = None
                _write_marker(root, value, env)
                return {"command_id": "owned-db-stop", "exit_status": code,
                        "previous_pid": observed["pid"], "pid": None,
                        "run_id": run_id, "data_directory": str(root / "data")}

            def start_database() -> dict:
                """Start only the same stopped marked cluster, then prove actual SQL."""
                checked_root, checked = _marker(env)
                if (checked_root != root or checked["pid"] is not None
                        or _pid(root, checked) is not None or binaries(PG_BIN) != hashes):
                    raise NativeQAError("Owned stopped database identity changed")
                code = _command([str(PG_BIN / "pg_ctl"), "-D", str(root / "data"),
                                 "-l", str(root / "postgres.log"), "-w", "-t", "30", "start"],
                                env=env, output=output, label="gate-db-start", password=password)
                value["pid"] = _pid(root, value)
                _write_marker(root, value, env)
                if code or value["pid"] is None:
                    raise NativeQAError("Owned database restart was not confirmed")
                observed = verify_owned_cluster(env)
                return {"command_id": "owned-db-start", "exit_status": code,
                        "pid": observed["pid"], "run_id": run_id,
                        "data_directory": observed["data_directory"]}

            session = run_session(source, output, root, env, run_id, manifest,
                                  stop_database, start_database, lambda: verify_owned_cluster(env))
            result.update(session)
            result["ok"] = session["completed_scenario"] is True
            phase = "post_session_workspace_unchanged"
            _verify_workspace(workspace_proof)
            (output / "workspace-after-session.json").write_text(
                json.dumps(workspace_proof, indent=2), encoding="utf-8"
            )
        phase = "source_unchanged"
        if _source_manifest(source) != manifest:
            raise NativeQAError("Release source changed during native QA")
        result["source_unchanged"] = True
        result["phase"] = "complete"
    except (NativeQAError, OSError, ValueError, KeyError, psycopg2.Error) as error:
        result["ok"] = False
        result["failure"] = _failure_event(phase, error)
        raise
    finally:
        os.chdir(previous)
        try:
            uninitialized = phase == "prepare_workspace"
            checked_root, checked = _marker(env, allow_uninitialized=uninitialized)
            pid = _pid(checked_root, checked)
            if pid is not None and _command(
                [
                    str(PG_BIN / "pg_ctl"),
                    "-D",
                    str(root / "data"),
                    "-m",
                    "fast",
                    "-w",
                    "-t",
                    "30",
                    "stop",
                ],
                env=env,
                output=output,
                label="stop",
                password=password,
            ):
                raise NativeQAError("Owned cluster stop failed; retained for inspection")
            if (root / "data/postmaster.pid").exists():
                raise NativeQAError("Refusing cleanup while postmaster PID remains")
            # Validate the same root/marker again immediately before recursive removal.
            if _marker(env, allow_uninitialized=uninitialized)[0] != root:
                raise NativeQAError("Cleanup root changed")
            server_log = root / "postgres.log"
            if server_log.is_file():
                log = server_log.read_text(encoding="utf-8", errors="replace")
                for secret in (password, token):
                    log = log.replace(secret, "<QA_SECRET_REDACTED>")
                (output / "postgres.log").write_text(log, encoding="utf-8")
            shutil.rmtree(root)
            cleanup = True
        except (NativeQAError, OSError, ValueError, KeyError, psycopg2.Error) as error:
            result["ok"] = False
            result["cleanup_failure"] = _failure_event("cleanup", error)
            raise
        finally:
            result["cleaned_owned_cluster"] = cleanup
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    """Require explicit source/output/account; never install packages or invoke Docker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--expected-os-user", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--gate-session", action="store_true",
                        help="After complete server checks, expose an owned private UDS browser session")
    args = parser.parse_args()
    if not 30 <= args.timeout <= 3600:
        parser.error("timeout must be 30..3600 seconds")
    try:
        result = run(args.source, args.output, args.work_root, args.expected_os_user, args.timeout,
                     gate_session=args.gate_session)
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    except (NativeQAError, OSError, ValueError, KeyError, psycopg2.Error):
        print(
            "NATIVE_QA_FAILED: inspect the new output directory; no existing cluster is a fallback",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
