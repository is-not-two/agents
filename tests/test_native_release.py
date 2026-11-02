"""Owned local release transactions: real loopback processes, no production deployment."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location("native_release_under_test", ROOT / "scripts/native_release.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


native = module()

FIXTURE_RUNNER = r'''
import argparse,json,os,signal,sys,time
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('action')
for name in ('release-root','shared-root','release-id','source-sha256','nonce','port'): p.add_argument('--'+name,required=True)
p.add_argument('--site-packages',default='')
a=p.parse_args()
mode=(Path(a.release_root)/'README.md').read_text().strip()
if a.action=='preflight':
    if mode=='preflight-timeout': time.sleep(20)
    sys.exit(3 if mode=='preflight-fail' else 0)
if mode=='exit': sys.exit(4)
if mode=='delayed-listen': time.sleep(1)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        identity={'release_id':a.release_id,'source_sha256':a.source_sha256,'nonce':a.nonce,'pid':os.getpid()}
        if mode=='wrong-identity': identity['nonce']='stale-process'
        body=json.dumps(identity if self.path=='/health/release' else {'status':'ok'}).encode()
        self.send_response(503 if mode=='unready' and self.path=='/health/ready' else 200)
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass
class Server(HTTPServer): allow_reuse_address=True
server=Server(('127.0.0.1',int(a.port)),Handler)
if mode=='close-listener':
    def linger(*args):
        server.server_close()
        time.sleep(20)
        sys.exit(0)
    signal.signal(signal.SIGTERM,linger)
server.serve_forever()
'''


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def approve(root, runtime_id="fixture", runner=FIXTURE_RUNNER):
    directory = root / "runtimes" / runtime_id
    directory.mkdir()
    path = directory / "runner.py"
    path.write_text(runner, encoding="utf-8")
    python = Path(sys._base_executable if os.name == "nt" else sys.executable)
    sites = Path(sys.prefix) / "Lib/site-packages" if os.name == "nt" and runtime_id == "actual" else None
    native.register_runtime(root, root, runtime_id, python, native.digest(path), sites)


def bundle(root, release_id, content="ok", *, files=None, runtime_id="fixture"):
    files = {"README.md": content.encode()} if files is None else files
    manifest = {name: native.hashlib.sha256(data).hexdigest() for name, data in files.items()}
    path = root / "inbox" / (release_id + ".zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("RELEASE-MANIFEST.json", json.dumps(manifest))
    sha = native.digest(path)
    path.with_suffix(".zip.sha256").write_text(sha + "  " + path.name + "\n", encoding="utf-8")
    gate = root / "inbox" / (release_id + "-gate.json")
    gate.write_text(json.dumps({"schema": 1, "passed": True, "level": "full", "source_manifest": manifest}), encoding="utf-8")
    return path, gate, sha, runtime_id


def stage(root, release_id, content="ok", **kwargs):
    path, gate, sha, runtime_id = bundle(root, release_id, content, **kwargs)
    return native.stage(root, root, release_id, runtime_id, path, gate, sha)


def stop_running(root):
    path = root / "RUNNING.json"
    if path.exists():
        state = json.loads(path.read_text())
        if native._process_identity(root, state):
            native._stop(root, state, 5)
    # Reap directly owned children on POSIX; never signal arbitrary processes.
    if os.name != "nt":
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if not pid:
                    break
            except ChildProcessError:
                break


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "managed"
    native.initialize(root, root)
    approve(root)
    try:
        yield root
    finally:
        stop_running(root)


def activate(root, release_id, current, port, **kwargs):
    return native.activate(root, root, release_id, current, port=port, schema_compatible=True,
                           timeout=kwargs.pop("timeout", 3), preflight_timeout=kwargs.pop("preflight_timeout", 3),
                           rollback_timeout=kwargs.pop("rollback_timeout", 3), **kwargs)


def test_native_release_stage_never_overwrites_and_hashes_every_file(installation):
    root = installation
    result = stage(root, "v1")
    assert result["staged"] and native._release(root, "v1")["source_sha256"] == result["source_sha256"]
    path, gate, sha, runtime_id = bundle(root, "again")
    with pytest.raises(FileExistsError):
        native.stage(root, root, "v1", runtime_id, path, gate, sha)
    (root / "releases/v1/README.md").write_text("tampered")
    with pytest.raises(native.ReleaseError, match="changed"):
        native._release(root, "v1")


def test_native_release_atomic_json_pointer_replace_failure_keeps_old(installation, monkeypatch):
    root = installation; stage(root, "old"); stage(root, "new")
    native._switch(root, "current", "old")
    path = root / "current.json"; before = path.read_bytes()
    assert json.loads(before) == {"schema": 1, "release_id": "old"}
    assert not path.is_symlink() and not (root / "current").exists()
    original = native.os.replace
    def denied(source, target):
        if Path(target) == path:
            raise PermissionError("simulated atomic publication failure")
        return original(source, target)
    monkeypatch.setattr(native.os, "replace", denied)
    with pytest.raises(PermissionError):
        native._switch(root, "current", "new")
    assert path.read_bytes() == before and native._pointer(root, "current") == "old"


@pytest.mark.parametrize("value", [{"schema": 1, "release_id": "../escape"},
                                   {"schema": True, "release_id": "old"},
                                   {"schema": 1, "release_id": "old", "target": "outside"}])
def test_native_release_json_pointer_rejects_path_and_schema_spoofs(installation, value):
    root = installation; stage(root, "old")
    (root / "current.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(native.ReleaseError):
        native._pointer(root, "current")


@pytest.mark.parametrize("bad", ["traversal", "absolute", "backslash", "symlink", "duplicate", "case_duplicate", "bomb", "extra", "gate", "sha"])
def test_native_release_unsafe_archives_never_become_releases(installation, bad):
    root = installation
    path, gate, sha, runtime_id = bundle(root, "unsafe")
    if bad in {"gate", "sha"}:
        if bad == "gate":
            data = json.loads(gate.read_text()); data["source_manifest"] = {"README.md": "0"*64}; gate.write_text(json.dumps(data))
        else:
            sha = "0"*64
    else:
        with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as archive:
            names = {"traversal": "../escape", "absolute": "/escape", "backslash": "src\\escape",
                     "duplicate": "README.md", "case_duplicate": "readme.MD", "extra": "data/private.json"}
            if bad == "symlink":
                item = zipfile.ZipInfo("src/link"); item.create_system = 3
                item.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(item, "../../outside")
            elif bad == "bomb":
                archive.writestr("src/bomb.txt", b"0" * 1024 * 1024)
            else:
                with pytest.warns(UserWarning) if bad == "duplicate" else native.contextlib.nullcontext():
                    archive.writestr(names[bad], b"bad")
        sha = native.digest(path)
        path.with_suffix(".zip.sha256").write_text(sha + "  " + path.name + "\n", encoding="ascii")
    with pytest.raises((native.ReleaseError, KeyError)):
        native.stage(root, root, "unsafe", runtime_id, path, gate, sha)
    assert not (root / "releases/unsafe").exists()
    assert not (root.parent / "escape").exists()


def test_native_release_true_process_switch_and_failure_previous_ready(installation):
    root = installation; port = free_port()
    for release_id, mode in [("v1", "ok"), ("v2", "ok"), ("broken", "unready")]:
        stage(root, release_id, mode)
    first = activate(root, "v1", "NONE", port)
    assert first["activated"] and native._pointer(root, "current") == "v1"
    second = activate(root, "v2", "v1", port)
    assert second["activated"] and second["pid"] != first["pid"]
    assert native._pointer(root, "previous") == "v1"
    failed = activate(root, "broken", "v2", port, timeout=0.6)
    assert not failed["activated"] and failed["previous_ready"]
    state = json.loads((root / "RUNNING.json").read_text())
    assert state["release_id"] == "v2" and native._identity(root, state)
    assert native._pointer(root, "current") == "v2" and not (root / "PENDING.json").exists()
    print(json.dumps({"proof": "native-fixture", "transition": ["v1", "v2", "broken", "v2"],
                      "source_sha256": native._release(root, "v2")["source_sha256"],
                      "identity_verified": native._identity(root, state), "previous_ready": failed["previous_ready"]}))


@pytest.mark.parametrize("mode", ["preflight-fail", "preflight-timeout", "wrong-identity", "exit"])
def test_native_release_preflight_and_health_fail_closed(installation, mode):
    root = installation; port = free_port()
    stage(root, "old"); stage(root, "bad", mode)
    activate(root, "old", "NONE", port)
    before = (root / "RUNNING.json").read_bytes()
    if mode.startswith("preflight"):
        with pytest.raises(native.ReleaseError):
            activate(root, "bad", "old", port, preflight_timeout=0.3)
        assert (root / "RUNNING.json").read_bytes() == before
    else:
        result = activate(root, "bad", "old", port, timeout=0.5)
        assert not result["activated"] and result["previous_ready"]
    assert native._pointer(root, "current") == "old"


def test_native_release_short_candidate_budget_does_not_shorten_previous_restart(installation):
    root = installation; port = free_port()
    stage(root, "old", "delayed-listen"); stage(root, "bad", "exit")
    assert activate(root, "old", "NONE", port)["activated"]
    result = activate(root, "bad", "old", port, timeout=0.2, rollback_timeout=3)
    state = json.loads((root / "RUNNING.json").read_text())
    assert not result["activated"] and result["previous_ready"]
    assert native._pointer(root, "current") == "old" and native._identity(root, state)
    assert not (root / "PENDING.json").exists()
    print(json.dumps({"proof": "independent-rollback-budget", "candidate_timeout_seconds": 0.2,
                      "rollback_timeout_seconds": 3, "previous_ready": result["previous_ready"]}))


@pytest.mark.parametrize("rollback_timeout", [0, 0.1, 121, float("inf"), float("nan")])
def test_native_release_rollback_timeout_is_bounded_before_any_launch(installation, rollback_timeout):
    root = installation; stage(root, "new")
    with pytest.raises(native.ReleaseError, match="bounded timeouts"):
        activate(root, "new", "NONE", free_port(), rollback_timeout=rollback_timeout)
    assert not (root / "PENDING.json").exists() and not (root / "RUNNING.json").exists()
    assert native._pointer(root, "current") == "NONE"


def test_native_release_expected_root_current_lock_schema_and_runner_pin(installation):
    root = installation; port = free_port(); stage(root, "v1")
    with pytest.raises(native.ReleaseError):
        native.activate(root, root.parent, "v1", "NONE", port=port, schema_compatible=True)
    with pytest.raises(native.ReleaseError):
        native.activate(root, root, "v1", "NONE", port=port, schema_compatible=False)
    with pytest.raises(native.ReleaseError):
        activate(root, "v1", "unreviewed", port)
    with native.locked(root), pytest.raises(FileExistsError):
        activate(root, "v1", "NONE", port)
    runner = root / "runtimes/fixture/runner.py"
    runner.write_text(runner.read_text() + "\n# changed")
    with pytest.raises(native.ReleaseError, match="changed"):
        activate(root, "v1", "NONE", port)
    assert native._pointer(root, "current") == "NONE"


def test_native_release_interrupt_compensates_and_crash_journal_recovers(installation, monkeypatch):
    root = installation; port = free_port(); stage(root, "old"); stage(root, "new")
    activate(root, "old", "NONE", port)
    original_wait = native._wait
    def interrupted(root, state, timeout, process=None):
        if state["release_id"] == "new":
            raise KeyboardInterrupt()
        return original_wait(root, state, timeout, process)
    monkeypatch.setattr(native, "_wait", interrupted)
    with pytest.raises(KeyboardInterrupt):
        activate(root, "new", "old", port)
    assert native._pointer(root, "current") == "old"
    old_state = json.loads((root / "RUNNING.json").read_text())
    assert native._identity(root, old_state)
    native._write(root / "PENDING.json", {"old": "old", "new": "new", "old_state": old_state,
                                         "candidate_state": None, "port": port})
    native._switch(root, "current", "new")
    result = native.recover(root, root, "new", 3)
    assert result["previous_ready"] and native._pointer(root, "current") == "old"


def test_native_release_cli_errors_do_not_echo_sensitive_environment(installation):
    secret = "DO_NOT_ECHO_NATIVE_SECRET"
    env = {**os.environ, "POSTGRES_PASSWORD": secret, "WORKSPACE_ACCESS_TOKEN": secret}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/native_release.py"), "activate",
                             "--project-root", str(installation), "--expected-project-root", str(installation),
                             "--release-id", "missing", "--expected-current", "NONE"],
                            env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 1 and secret not in result.stdout + result.stderr


def test_native_release_stop_requires_identity_not_database_readiness(installation):
    root = installation; stage(root, "unready", "unready"); port = free_port()
    process, state = native._start(root, "unready", port)
    try:
        deadline = time.monotonic() + 5
        while not native._process_identity(root, state) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert native._process_identity(root, state) and not native._identity(root, state)
        wrong = {**state, "pid": os.getpid()}
        with pytest.raises(native.ReleaseError, match="refusing"):
            native._stop(root, wrong, 1)
        assert process.poll() is None
        native._stop(root, state, 3)
        assert native._exited(state)
        process.wait(timeout=3)
    finally:
        native._kill_own(process, 3)


def test_native_release_unicode_packager_checksum(installation):
    root = installation
    path, gate, sha, runtime_id = bundle(root, "中文发布")
    # release identities remain portable ASCII; package filenames need not be ASCII.
    assert native.stage(root, root, "unicode", runtime_id, path, gate, sha)["staged"]


def test_native_release_crash_start_journal_gap_never_kills_unknown_process(installation):
    root = installation; stage(root, "old"); stage(root, "new"); port = free_port()
    activate(root, "old", "NONE", port)
    old_state = json.loads((root / "RUNNING.json").read_text())
    native._stop(root, old_state, 3)
    native._switch(root, "current", "new")
    orphan, orphan_state = native._start(root, "new", port)
    try:
        native._wait(root, orphan_state, 3, orphan)
        native._write(root / "PENDING.json", {"old": "old", "new": "new", "old_state": old_state,
                                             "candidate_state": None, "launch_intent": True, "port": port})
        with pytest.raises(native.ReleaseError):
            native.recover(root, root, "new", 0.5)
        assert orphan.poll() is None and (root / "PENDING.json").exists()
    finally:
        native._kill_own(orphan, 3)
        journal = json.loads((root / "PENDING.json").read_text())
        journal["candidate_state"] = orphan_state
        native._write(root / "PENDING.json", journal, replace=True)
        native.recover(root, root, native._pointer(root, "current"), 3)


@pytest.mark.parametrize("old", ["NONE", "old"])
def test_native_release_restore_uncertain_launch_keeps_pending_before_pointer_change(installation, monkeypatch, old):
    """No endpoint or PID is evidence of uncertainty, not proof of successful recovery."""
    root = installation
    pending = {"old": old, "new": "new", "old_state": None, "candidate_state": None,
               "launch_intent": True, "port": free_port()}
    native._write(root / "PENDING.json", pending)
    def no_pointer_change(*args):
        pytest.fail("uncertain launch must not switch a pointer")
    monkeypatch.setattr(native, "_switch", no_pointer_change)
    with pytest.raises(native.ReleaseError, match="uncertain launch"):
        native._restore(root, pending, 0.2)
    assert json.loads((root / "PENDING.json").read_text()) == pending


def test_native_release_bootstrap_start_gap_retains_pending_for_delayed_child(installation, monkeypatch):
    root = installation; stage(root, "new", "delayed-listen"); port = free_port()
    original = native._start; children = []
    def crash_after_start(*args):
        process, state = original(*args)
        children.append((process, state))
        # Simulate controller loss after Popen and before the durable PID state.
        raise KeyboardInterrupt()
    monkeypatch.setattr(native, "_start", crash_after_start)
    try:
        with pytest.raises(native.ReleaseError, match="PENDING retained"):
            activate(root, "new", "NONE", port)
        assert len(children) == 1 and children[0][0].poll() is None
        assert not native._process_identity(root, children[0][1])
        pending = json.loads((root / "PENDING.json").read_text())
        assert pending["launch_intent"] and pending["candidate_state"] is None
        with pytest.raises(native.ReleaseError, match="uncertain launch"):
            native.recover(root, root, "new", 0.2)
        assert (root / "PENDING.json").exists() and children[0][0].poll() is None
    finally:
        for process, state in children:
            native._kill_own(process, 3)
            pending = json.loads((root / "PENDING.json").read_text())
            pending["candidate_state"] = state
            native._write(root / "PENDING.json", pending, replace=True)
        if children:
            result = native.recover(root, root, "new", 3)
            assert result == {"recovered": True, "current": "NONE", "previous_ready": False}


def test_native_release_restore_live_unready_old_does_not_launch_duplicate(installation, monkeypatch):
    root = installation; stage(root, "old", "unready"); port = free_port()
    process, state = native._start(root, "old", port)
    try:
        deadline = time.monotonic() + 5
        while not native._process_identity(root, state) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert native._process_identity(root, state) and not native._identity(root, state)
        pending = {"old": "old", "new": "new", "old_state": state,
                   "candidate_state": None, "launch_intent": False, "port": port}
        native._write(root / "PENDING.json", pending)
        def no_duplicate(*args):
            pytest.fail("DB unready must not duplicate a live previous process")
        monkeypatch.setattr(native, "_start", no_duplicate)
        with pytest.raises(native.ReleaseError, match="readiness"):
            native._restore(root, pending, 0.2)
        assert process.poll() is None and (root / "PENDING.json").exists()
        assert native._pointer(root, "current") == "old"
    finally:
        native._kill_own(process, 3)


def test_native_release_restore_restart_gap_retains_pending_without_second_start(installation, monkeypatch):
    root = installation; stage(root, "old"); stage(root, "new"); port = free_port()
    assert activate(root, "old", "NONE", port)["activated"]
    old_state = json.loads((root / "RUNNING.json").read_text())
    native._stop(root, old_state, 3)
    pending = {"old": "old", "new": "new", "old_state": old_state,
               "candidate_state": None, "launch_intent": False, "port": port}
    native._write(root / "PENDING.json", pending)
    original = native._start; children = []
    def crash_after_restore_start(*args):
        process, state = original(*args)
        children.append((process, state))
        raise KeyboardInterrupt()
    monkeypatch.setattr(native, "_start", crash_after_restore_start)
    try:
        with pytest.raises(KeyboardInterrupt):
            native._restore(root, pending, 3)
        journal = json.loads((root / "PENDING.json").read_text())
        assert journal["restore_launch_intent"] and journal["restored_state"] is None
        with pytest.raises(native.ReleaseError, match="previous-process launch journal gap"):
            native.recover(root, root, "old", 0.2)
        assert len(children) == 1 and children[0][0].poll() is None
    finally:
        monkeypatch.setattr(native, "_start", original)
        for process, state in children:
            native._kill_own(process, 3)
            journal = json.loads((root / "PENDING.json").read_text())
            journal["restored_state"] = state
            native._write(root / "PENDING.json", journal, replace=True)
        if children:
            assert native.recover(root, root, "old", 3)["previous_ready"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux pidfd exit-vs-listener adversarial fixture")
def test_native_release_stop_waits_for_os_exit_not_listener_loss(installation):
    root = installation; stage(root, "lingering", "close-listener"); port = free_port()
    process, state = native._start(root, "lingering", port)
    try:
        native._wait(root, state, 3, process)
        with pytest.raises(native.ReleaseError, match="endpoint loss is not process exit"):
            native._stop(root, state, 0.2)
        assert process.poll() is None and not native._exited(state)
        assert not native._process_identity(root, state)
    finally:
        native._kill_own(process, 0.2)


@pytest.mark.skipif(os.name != "nt", reason="Windows venv redirector PID boundary")
def test_native_release_windows_venv_redirector_is_not_approved(installation):
    directory = installation / "runtimes" / "redirector"
    directory.mkdir()
    runner = directory / "runner.py"; runner.write_text(FIXTURE_RUNNER, encoding="utf-8")
    venv_python = ROOT / ".venv/Scripts/python.exe"
    if not venv_python.is_file():
        pytest.skip("repository test venv is not present")
    with pytest.raises(native.ReleaseError, match="venv redirectors"):
        native.register_runtime(installation, installation, "redirector", venv_python, native.digest(runner))
    assert not (directory / "APPROVED.json").exists()


@pytest.mark.skipif(not os.environ.get("SHILIE_QA_RUN_ID"), reason="requires coordinator-owned QA PostgreSQL")
def test_native_release_actual_production_app_upgrade_and_recovery(tmp_path, monkeypatch):
    """Actual app+uvicorn, production verify-only and a fresh restricted DB role; never production."""
    assert os.environ.get("POSTGRES_DB") == "regression" and os.environ.get("POSTGRES_HOST") == "127.0.0.1"
    import secrets

    import yaml
    from psycopg2 import sql

    from rag_tech_retriever.common.release_manifest import source_manifest
    from rag_tech_retriever.platform.record_store import RecordStore

    root = tmp_path / "native-install"; native.initialize(root, root)
    approve(root, "actual", (ROOT / "scripts/native_app_runner.py").read_text(encoding="utf-8"))
    prefix = "qa_native_" + uuid4().hex[:10]
    owner = RecordStore(prefix); owner.ensure_schema()
    owner.save("knowledge", {"title": "release DB unchanged", "content": "owned QA only"})
    def database_hash():
        with owner.transaction() as cur:
            cur.execute(f"SELECT row_to_json(r) AS row FROM {owner.records} r ORDER BY id")
            records = cur.fetchall()
            cur.execute(f"SELECT row_to_json(r) AS row FROM {owner.versions} r ORDER BY record_id,version")
            versions = cur.fetchall()
            cur.execute("SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid IN (%s::regclass,%s::regclass) ORDER BY conname", (owner.records, owner.versions))
            constraints = cur.fetchall()
        return native.hashlib.sha256(json.dumps([records, versions, constraints], sort_keys=True, default=str).encode()).hexdigest()
    database_before = database_hash()
    role = "qa_native_" + uuid4().hex[:10]; password = secrets.token_urlsafe(32)
    admin_env = {key: os.environ.get(key) for key in ("POSTGRES_USER", "POSTGRES_PASSWORD")}
    with owner.transaction() as cur:
        cur.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Identifier(role)), (password,))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        cur.execute(sql.SQL(f"GRANT SELECT,INSERT,UPDATE ON {owner.records} TO {{}}").format(sql.Identifier(role)))
        cur.execute(sql.SQL(f"GRANT SELECT,INSERT ON {owner.versions} TO {{}}").format(sql.Identifier(role)))
    try:
        # Build frozen test source, not the live checkout; package and gate share its exact manifest.
        source = tmp_path / "frozen-source"; source.mkdir()
        shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__", "_archived", "*.pyc", "*.png"))
        shutil.copytree(ROOT / "config", source / "config")
        web = source / "config/web.yaml"; data = yaml.safe_load(web.read_text(encoding="utf-8"))
        data["web"]["table_prefix"] = prefix
        web.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        # This is the operator's explicit one-time QA configuration, not an
        # implicit controller copy from a release on each start/upgrade.
        shutil.copytree(source / "config", root / "shared/config")
        release_hashes = {}
        for release_id in ("actual-old", "actual-new", "actual-bad"):
            (source / "README.md").write_text(release_id, encoding="utf-8")
            if release_id == "actual-bad":
                route = source / "src/rag_tech_retriever/api/routes/operations.py"
                text = route.read_text(encoding="utf-8")
                assert 'ok = database_ready()' in text
                route.write_text(text.replace('ok = database_ready()', 'ok = False  # deliberate failed-readiness test fixture'), encoding="utf-8")
            manifest = source_manifest(source)
            files = {name: (source / name).read_bytes() for name in manifest}
            release_hashes[release_id] = stage(root, release_id, files=files, runtime_id="actual")["source_sha256"]
        for key, value in {"POSTGRES_USER": role, "POSTGRES_PASSWORD": password,
                           "WORKSPACE_REQUIRE_AUTH": "true", "WORKSPACE_ACCESS_TOKEN": "w"*40,
                           "WORKSPACE_MCP_TOKEN": "", "WEB_RATE_LIMIT_PER_MINUTE": "120",
                           "PROJECT_ROOT": str(tmp_path / "wrong-inherited-root")}.items():
            monkeypatch.setenv(key, value)
        port = free_port()
        def api(method, path, payload=None):
            data = json.dumps(payload).encode() if payload is not None else None
            request = native.urllib.request.Request(f"http://127.0.0.1:{port}" + path, data,
                {"Authorization": "Bearer " + os.environ["WORKSPACE_ACCESS_TOKEN"],
                 "Content-Type": "application/json"}, method=method)
            opener = native.urllib.request.build_opener(native.urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=10) as response:
                return json.load(response)
        first = activate(root, "actual-old", "NONE", port, timeout=20, preflight_timeout=30, rollback_timeout=20)
        assert first["activated"]
        assert api("POST", "/api/private/setup", {"password": "QA-local-only-password"})["ok"]
        connection = api("GET", "/api/model-connection")
        saved_connection = api("PUT", "/api/model-connection", {"revision": connection["revision"],
            "api_key": "fake-local-only-not-used", "base_url": "https://example.invalid/v1", "model": "qa-never-invoked"})
        saved_stage = api("POST", "/api/stages", {"title": "shared persistence QA", "objective": "no production data"})
        shared_files = ["data/local/private-vault.json", "data/local/llm-connection.json",
                        "output/stages/" + saved_stage["id"] + "/record.json"]
        shared_hashes = {name: native.digest(root / "shared" / name) for name in shared_files}
        second = activate(root, "actual-new", "actual-old", port, timeout=20, preflight_timeout=30, rollback_timeout=20)
        assert second["activated"] and first["pid"] != second["pid"]
        assert api("GET", "/api/private/status")["configured"]
        assert api("GET", "/api/model-connection")["revision"] == saved_connection["revision"]
        assert saved_stage["id"] in {record["id"] for record in api("GET", "/api/stages")}
        failed = activate(root, "actual-bad", "actual-new", port, timeout=3, preflight_timeout=30, rollback_timeout=20)
        assert not failed["activated"] and failed["previous_ready"]
        assert native._pointer(root, "current") == "actual-new"
        database_after = database_hash()
        assert database_after == database_before
        assert {name: native.digest(root / "shared" / name) for name in shared_files} == shared_hashes
        assert not (tmp_path / "wrong-inherited-root").exists()
        for release_id, source_sha in release_hashes.items():
            assert native._release(root, release_id)["source_sha256"] == source_sha
            assert not (root / "releases" / release_id / "data").exists()
        running = json.loads((root / "RUNNING.json").read_text())
        print(json.dumps({"proof": "native-actual-app-owned-QA", "profile": "production", "restricted_role": True,
                          "transition": ["actual-old", "actual-new", "actual-bad", "actual-new"],
                          "source_sha256": native._release(root, "actual-new")["source_sha256"],
                          "identity_verified": native._identity(root, running), "previous_ready": failed["previous_ready"],
                          "shared_files_preserved": True, "staged_source_unchanged": True,
                          "candidate_timeout_seconds": 3, "rollback_timeout_seconds": 20,
                          "database_sha256_before": database_before, "database_sha256_after": database_after}))
    finally:
        stop_running(root)
        for key, value in admin_env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        with owner.transaction() as cur:
            cur.execute(sql.SQL(f"REVOKE ALL ON {owner.records},{owner.versions} FROM {{}}").format(sql.Identifier(role)))
            cur.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(sql.Identifier(role)))
            cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            cur.execute(f"DROP TABLE {owner.versions}")
            cur.execute(f"DROP TABLE {owner.records}")
