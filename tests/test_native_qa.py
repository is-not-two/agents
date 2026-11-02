"""Native UDS protocol boundaries; actual browser/PG actions remain integration evidence."""

import copy
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("owned_qa_test_" + name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load("native_gate_server")
qa = load("native_qa")
RUN, SESSION, MANIFEST = "a" * 12, "b" * 32, "c" * 64


def request(operation="db-stop", seq=1, identity=None):
    return {"schema": 1, "run_id": RUN, "session_id": SESSION, "seq": seq,
            "request_id": identity or f"{seq:032x}", "operation": operation}


@pytest.fixture
def controller(tmp_path):
    calls = []
    actions = {name: (lambda name=name: calls.append(name) or {"command_id": name, "exit_status": 0})
               for name in gate.OPERATIONS if name != "finish"}
    return gate.ControlState(tmp_path, RUN, SESSION, MANIFEST, actions), calls


def test_native_control_sequence_receipts_and_response_loss_replay(controller):
    state, calls = controller
    previous = "0" * 64
    for seq, operation in enumerate(gate.OPERATIONS, 1):
        value = request(operation, seq)
        receipt = state.execute(value)
        assert receipt["ok"] and receipt["previous_receipt_sha256"] == previous
        assert receipt["receipt_sha256"] == gate.sha({k: v for k, v in receipt.items() if k != "receipt_sha256"})
        assert state.execute(value) == receipt
        previous = receipt["receipt_sha256"]
    assert calls == ["db-stop", "db-start", "app-restart"]
    assert state.status()["last_seq"] == 4 and state.completed_scenario
    assert state.state == "finishing"


def test_native_server_receipts_match_the_actual_desktop_client_verifier(controller):
    """Exercise both real protocol implementations without any SSH or HTTP."""
    client = load("native_gate_client")
    public = {"run_id": RUN, "session_id": SESSION, "source_manifest_sha256": MANIFEST}
    verifier = client.Control(SimpleNamespace(control_port=18001), public, "unused-private-fixture")
    state, calls = controller
    for seq, operation in enumerate(gate.OPERATIONS, 1):
        value = request(operation, seq)
        receipt = state.execute(value)
        verifier.verify_receipt(json.loads(json.dumps(receipt)), value)
    assert verifier.seq == 4 and verifier.previous == state.last_receipt
    assert verifier.receipts[-1]["completed_scenario"] and len(calls) == 3


def test_native_finish_early_only_requests_cleanup(controller):
    state, calls = controller
    receipt = state.execute(request("finish"))
    assert receipt["ok"] and not receipt["completed_scenario"] and not calls


@pytest.mark.parametrize("change", [
    {"schema": True}, {"schema": 2}, {"run_id": "d" * 12}, {"session_id": "d" * 32},
    {"seq": True}, {"seq": 0}, {"seq": 2}, {"request_id": "../target"},
    {"request_id": 1}, {"operation": "drop-database"}, {"operation": "db-start"},
    {"operation": "app-restart"}, {"command": "arbitrary"},
])
def test_native_control_rejects_unbound_or_out_of_order_before_action(controller, change):
    state, calls = controller
    with pytest.raises(gate.GateSessionError):
        state.execute({**request(), **change})
    assert not calls and state.last_seq == 0


def test_native_request_id_cannot_be_reused_for_a_different_action(controller):
    state, calls = controller
    value = request()
    state.execute(value)
    with pytest.raises(gate.GateSessionError, match="reused"):
        state.execute({**value, "operation": "finish"})
    assert calls == ["db-stop"]


def test_native_uncertain_intent_never_reexecutes(controller):
    state, calls = controller
    value = request()
    gate._fresh_json(state.output / ("control-" + value["request_id"] + ".json"),
                     {"status": "intent", "request_sha256": gate.sha(value)})
    with pytest.raises(gate.GateSessionError, match="never repeated"):
        state.execute(value)
    with pytest.raises(gate.GateSessionError, match="out of order"):
        state.execute(request(identity="e" * 32))
    assert state.execute(request("finish", identity="f" * 32))["completed_scenario"] is False
    assert not calls


def test_native_action_failure_is_uncertain_and_does_not_echo_secret(controller):
    state, calls = controller
    def fail():
        calls.append("attempt")
        raise RuntimeError("SYNTHETIC_SECRET")
    state.actions["db-stop"] = fail
    receipt = state.execute(request())
    assert not receipt["ok"] and receipt["after"] == "uncertain"
    assert "SYNTHETIC_SECRET" not in json.dumps(receipt)
    assert state.execute(request()) == receipt and calls == ["attempt"]
    with pytest.raises(gate.GateSessionError):
        state.execute(request("db-stop", 2))
    assert not state.execute(request("finish", 2))["completed_scenario"]


def test_native_commit_failure_blocks_new_id_reexecution(controller, monkeypatch):
    state, calls = controller
    original = gate._replace_json
    failed = False
    def fault(path, value):
        nonlocal failed
        if path.name.startswith("control-") and not failed:
            failed = True
            raise OSError("SYNTHETIC_SECRET")
        return original(path, value)
    monkeypatch.setattr(gate, "_replace_json", fault)
    with pytest.raises(OSError):
        state.execute(request())
    with pytest.raises(gate.GateSessionError):
        state.execute(request(identity="d" * 32))
    with pytest.raises(gate.GateSessionError, match="never repeated"):
        state.execute(request())
    assert calls == ["db-stop"]
    assert not state.execute(request("finish", identity="f" * 32))["completed_scenario"]


def test_native_corrupt_cached_receipt_is_not_returned(controller):
    state, calls = controller
    value = request()
    state.execute(value)
    path = state.output / ("control-" + value["request_id"] + ".json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["receipt"]["ok"] = False
    gate._replace_json(path, saved)
    with pytest.raises(gate.GateSessionError, match="receipt changed"):
        state.execute(value)
    assert calls == ["db-stop"]


@pytest.mark.parametrize("data", [b'[]', b'{"schema":1,"schema":2}', b'{"seq":NaN}',
                                 b'{"seq":Infinity}', b'\xff', '{"schema":1}'.encode("utf-16")])
def test_native_decode_rejects_ambiguous_non_utf8_or_nonfinite_objects(data):
    with pytest.raises((ValueError, UnicodeError)):
        gate.decode_request(data)


@pytest.mark.parametrize("given,peer,expected", [("Bearer secret", 994, True),
    ("Bearer secret", 0, True), ("Bearer secret", 995, False),
    ("Bearer wrong", 994, False), ("Bearer sécret", 994, False), ("", 994, False)])
def test_native_control_requires_secret_and_allowed_os_peer(given, peer, expected):
    assert gate.authorized(given, "secret", peer, 994) is expected


def marker_environment(tmp_path, monkeypatch, *, pid=None):
    root = tmp_path / "shilie-native-qa-case"
    root.mkdir(mode=0o700)
    uid = os.geteuid() if hasattr(os, "geteuid") else 0
    monkeypatch.setattr(qa, "_linux_user", lambda *_: uid)
    if os.name == "nt":
        # Windows unit simulation cannot prove POSIX owner/mode semantics.
        def owned(path, _uid, *, directory=False):
            info = path.lstat()
            assert stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        monkeypatch.setattr(qa, "_owned", owned)
    env = {"SHILIE_QA_RUN_ID": RUN, "SHILIE_QA_NATIVE_ROOT": str(root),
           "SHILIE_QA_NATIVE_TOKEN": "private-token", "SHILIE_QA_NATIVE_BIN": str(qa.PG_BIN),
           "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "55433"}
    value = {"uid": uid, "run_id": RUN, "root": str(root), "data_directory": str(root / "data"),
             "cluster_name": "shilie_qa_" + RUN,
             "token_sha256": hashlib.sha256(env["SHILIE_QA_NATIVE_TOKEN"].encode()).hexdigest(),
             "port": 55433, "bin": str(qa.PG_BIN), "pid": pid}
    qa._write_marker(root, value, env)
    return root, value, env


def test_native_pre_init_marker_allows_missing_data_only_by_explicit_internal_flag(tmp_path, monkeypatch):
    root, _, env = marker_environment(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        qa._marker(env)
    assert qa._marker(env, allow_uninitialized=True)[0] == root
    bad = copy.deepcopy(env)
    bad["SHILIE_QA_NATIVE_TOKEN"] = "wrong"
    with pytest.raises(qa.NativeQAError):
        qa._marker(bad, allow_uninitialized=True)


def test_native_initialized_marker_must_not_lose_data_directory(tmp_path, monkeypatch):
    _, _, env = marker_environment(tmp_path, monkeypatch, pid=4242)
    with pytest.raises(qa.NativeQAError, match="cannot lose"):
        qa._marker(env, allow_uninitialized=True)


def test_native_pre_init_missing_fixture_cleans_only_new_owned_root_without_pg_command(tmp_path, monkeypatch):
    source, work, output = tmp_path / "source", tmp_path / "work", tmp_path / "evidence"
    (source / "scripts").mkdir(parents=True)
    (source / "config").mkdir()
    (source / "pyproject.toml").write_text("", encoding="utf-8")
    (source / "scripts/seed_ci_corpus.py").write_text("", encoding="utf-8")
    work.mkdir()
    uid = os.geteuid() if hasattr(os, "geteuid") else 0
    monkeypatch.setattr(qa, "_linux_user", lambda *_: uid)
    monkeypatch.setattr(qa.os, "geteuid", lambda: uid, raising=False)
    monkeypatch.setattr(qa, "binaries", lambda *_: {})
    monkeypatch.setattr(qa, "_source_manifest", lambda *_: {})
    if os.name == "nt":
        monkeypatch.setattr(qa, "_owned", lambda path, *_args, **_kwargs: path.lstat())
    monkeypatch.setattr(qa, "_command", lambda *_args, **_kwargs: pytest.fail("No initdb/PG command allowed"))
    with pytest.raises(qa.NativeQAError, match="static regular"):
        qa.run(source, output, work, "dedicated-unit-only", 30)
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert result["failure"]["phase"] == "prepare_workspace"
    assert result["cleaned_owned_cluster"] is True and "cleanup_failure" not in result
    assert list(work.iterdir()) == []


def test_native_browser_config_keeps_base_but_leaves_qa_policies_fresh(tmp_path):
    source, root, output = tmp_path / "source", tmp_path / "browser", tmp_path / "output"
    (source / "config").mkdir(parents=True)
    root.mkdir(); output.mkdir()
    for name in ["settings.yaml", "prompts.yaml", "web.yaml", "corpora.yaml", "mcp.yaml", "public-sources.json"]:
        (source / "config" / name).write_text("{}", encoding="utf-8")
    copied = gate._browser_configuration(source, root, output)
    assert set(copied) == {"settings.yaml", "prompts.yaml", "web.yaml"}
    assert sorted(p.name for p in (root / "config").iterdir()) == sorted(copied)
    assert not (root / ".env").exists()


def test_native_critical_junit_proof_does_not_confuse_skips_with_execution(tmp_path):
    path = tmp_path / "junit.xml"
    names = {"test_native_backup": ["test_integration_native_backup_restore_and_transaction_failure"],
             "test_native_release": ["test_native_release_actual_production_app_upgrade_and_recovery", "test_native_release_stop_waits_for_os_exit_not_listener_loss"],
             "test_native_schema": ["test_restricted_production_account_starts_and_crud_without_ddl", "test_valid_schema_verification_is_readonly_and_local_old_upgrade_preserves_history"]}
    content = '<testsuites><testsuite>' + ''.join(f'<testcase classname="tests.{module}" name="{name}" />'
              for module, cases in names.items() for name in cases) + '</testsuite></testsuites>'
    path.write_text(content, encoding="utf-8")
    assert qa._pytest_proof(path)["critical_native_passed"]
    path.write_text(content.replace('name="test_integration_native_backup_restore_and_transaction_failure" />',
        'name="test_integration_native_backup_restore_and_transaction_failure"><skipped message="owned cluster missing" /></testcase>'), encoding="utf-8")
    proof = qa._pytest_proof(path)
    assert not proof["critical_native_passed"] and proof["skipped"][0]["reason"] == "owned cluster missing"


def test_native_application_stop_confirms_exit_even_after_terminate_timeout(tmp_path):
    app = gate.OwnedApplication(tmp_path, tmp_path, tmp_path, {}, RUN, 994)
    calls = []
    class Child:
        pid, returncode = 12345, None
        def poll(self):
            return self.returncode
        def terminate(self):
            calls.append("terminate")
        def wait(self, timeout):
            calls.append(("wait", timeout))
            if self.returncode is None:
                raise subprocess.TimeoutExpired("owned-fixture", timeout)
        def kill(self):
            calls.append("kill")
            self.returncode = -9
    app.process = Child()
    result = app.stop()
    assert result["exit_status"] == -9 and app.process is None
    assert calls == ["terminate", ("wait", 15), "kill", ("wait", 10)]


@pytest.mark.skipif(os.name != "posix", reason="Real POSIX private credential inode/mode cleanup")
@pytest.mark.parametrize("change", ["none", "content", "inode"])
def test_native_credential_cleanup_never_unlinks_a_changed_inode(tmp_path, change):
    path = tmp_path / "session-secrets.json"
    value = {"control_token": "private-fixture-not-printed"}
    gate._fresh_json(path, value)
    info = path.lstat()
    identity = (info.st_dev, info.st_ino)
    if change == "content":
        path.write_bytes(b'{"changed":true}')
    elif change == "inode":
        other = tmp_path / "replacement"
        gate._fresh_json(other, value)
        os.replace(other, path)
    if change == "none":
        gate._remove_secret(path, os.geteuid(), identity, gate.sha(value))
        assert not path.exists()
    else:
        with pytest.raises(gate.GateSessionError):
            gate._remove_secret(path, os.geteuid(), identity, gate.sha(value))
        assert path.exists()
