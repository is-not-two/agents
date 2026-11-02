"""Offline native-client boundary tests; never start SSH, Docker or a browser."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "native_gate_client", Path(__file__).resolve().parents[1] / "scripts/native_gate_client.py"
)
assert SPEC and SPEC.loader
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


@pytest.fixture(autouse=True)
def no_accidental_subprocess(monkeypatch):
    """An unexpected subprocess/network call is a test failure, not an integration test."""
    def blocked(*args, **kwargs):
        raise AssertionError("Offline test attempted an external process or HTTP request")
    monkeypatch.setattr(client.subprocess, "run", blocked)
    monkeypatch.setattr(client.subprocess, "Popen", blocked)
    monkeypatch.setattr(client.urllib.request.OpenerDirector, "open", blocked)


@pytest.fixture
def transport(tmp_path, monkeypatch):
    identity = tmp_path / "identity"; identity.write_text("unused-private-fixture", encoding="ascii")
    hosts = tmp_path / "known_hosts"
    raw = b"public-host-key-fixture-only"
    encoded = base64.b64encode(raw).decode()
    pin = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
    monkeypatch.setattr(client, "HOST_PIN", pin)
    hosts.write_text(client.HOST + " ssh-ed25519 " + encoded + "\n", encoding="ascii")
    value = {"schema": 1, "host": client.HOST, "port": 22, "user": "root",
             "identity_file": str(identity), "known_hosts": str(hosts),
             "expected_host_fingerprint": pin,
             "remote_output": client.REMOTE_BASE + "/native-qa99"}
    path = tmp_path / "transport.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


@pytest.fixture
def session(transport):
    _, value = transport
    manifest = {"README.md": "a" * 64}
    now = datetime.now(timezone.utc)
    public = {"schema": 1, "kind": "shilie/native-gate-session", "run_id": "a" * 12,
              "session_id": "b" * 32, "uid": 994, "source_manifest": manifest,
              "source_manifest_sha256": client.digest(manifest), "state": "ready",
              "created_at": now.isoformat(), "expires_at": (now + timedelta(minutes=15)).isoformat(),
              "token_sha256": hashlib.sha256(("c" * 48).encode()).hexdigest()}
    for field, name in (("api_socket", "api.sock"), ("control_socket", "control.sock"),
                        ("status_path", "gate-status.json"), ("secrets_path", "session-secrets.json")):
        public[field] = value["remote_output"] + "/" + name
    secrets = {"schema": 1, "run_id": public["run_id"], "session_id": public["session_id"],
               "control_token": "c" * 48, "mcp_token": "m" * 48}
    raw = {"uid": 994, "files": {"session-public.json": json.dumps(public),
                                  "session-secrets.json": json.dumps(secrets)}}
    return manifest, public, secrets, raw


def test_decode_bounded_duplicate_nonfinite_and_native_json():
    assert client.decode(b'{"native":"\xe4\xb8\xad\xe6\x96\x87"}') == {"native": "中文"}
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'\xff', b'{'):
        with pytest.raises(client.ClientError):
            client.decode(raw)
    with pytest.raises(client.ClientError, match="SIZE"):
        client.decode(b'{}', 1)


def test_transport_ignores_no_fields_and_pins_exact_host(transport):
    path, value = transport
    assert client.load_transport(path) == value
    args = client.ssh_arguments(value)
    assert args[1:4] == ["-F", "none", "-T"]
    assert "StrictHostKeyChecking=yes" in args and "ClearAllForwardings=yes" in args
    assert "PasswordAuthentication=no" in args and "ProxyCommand=none" in args
    assert "ForwardAgent=no" in args and "ControlPath=none" in args


@pytest.mark.parametrize("key,value", [
    ("host", "example.invalid"), ("host", "8.156.81.128;id"), ("port", True),
    ("port", 2222), ("user", "nobody"), ("expected_host_fingerprint", "other"),
    ("remote_output", "/etc/shilie"),
    ("remote_output", client.REMOTE_BASE + "/../shilie"),
    ("remote_output", client.REMOTE_BASE + "/native-qa99\ncommand"),
    ("command", "cat /etc/shilie/workspace.env"),
])
def test_transport_rejects_unapproved_hosts_paths_or_command_fields(transport, key, value):
    path, original = transport
    path.write_text(json.dumps({**original, key: value}), encoding="utf-8")
    with pytest.raises(client.ClientError):
        client.load_transport(path)


def test_transport_rejects_nonexclusive_known_hosts_and_pin(transport):
    path, value = transport
    hosts = Path(value["known_hosts"])
    original = hosts.read_text(encoding="ascii")
    for raw in (original + original, "other " + original.split(" ", 1)[1], "# empty\n"):
        hosts.write_text(raw, encoding="ascii")
        with pytest.raises(client.ClientError):
            client.load_transport(path)


def test_session_exact_source_uid_paths_time_and_credentials(transport, session):
    manifest, public, secrets, raw = session
    assert client.validate_session(raw, transport[1], manifest) == (public, secrets)
    assert "session-secrets.json" in client.remote_script(transport[1], "initial").decode()
    script = client.remote_script(transport[1], "final").decode()
    assert "session-secrets.json'," not in script
    assert "stat.S_ISSOCK" in script
    for mode in ("initial", "final"):
        compile(client.remote_script(transport[1], mode), "<fixed-read-only-remote-template>", "exec")
    with pytest.raises(client.ClientError):
        client.remote_script(transport[1], "arbitrary-command")


@pytest.mark.parametrize("key,value", [
    ("run_id", "z" * 12), ("session_id", "short"), ("schema", True),
    ("state", "db-offline"), ("uid", 0), ("source_manifest", {}),
    ("source_manifest_sha256", "f" * 64), ("api_socket", "/run/postgresql/.s.PGSQL.5432"),
    ("control_socket", "/etc/shilie/control.sock"), ("token_sha256", "0" * 64),
    ("expires_at", "2000-01-01T00:00:00Z"), ("created_at", "2099-01-01T00:00:00Z"),
])
def test_session_rejects_replay_foreign_source_paths_and_expiry(transport, session, key, value):
    manifest, public, _secrets, raw = session
    raw["files"]["session-public.json"] = json.dumps({**public, key: value})
    with pytest.raises(client.ClientError):
        client.validate_session(raw, transport[1], manifest)


@pytest.mark.parametrize("change", [{"schema": True}, {"control_token": "m" * 48},
                                   {"extra": "not allowed"}, {"mcp_token": "short"},
                                   {"session_id": "f" * 32}])
def test_secrets_strict_identity_independent_tokens(transport, session, change):
    manifest, _public, secrets, raw = session
    raw["files"]["session-secrets.json"] = json.dumps({**secrets, **change})
    with pytest.raises(client.ClientError):
        client.validate_session(raw, transport[1], manifest)


def test_remote_read_secrets_stay_in_memory_not_stdout(transport, session, monkeypatch, capsys):
    _, _, secrets, raw = session
    calls = []
    def fake(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, json.dumps(raw).encode(), b"")
    monkeypatch.setattr(client.subprocess, "run", fake)
    assert client.remote_read(transport[1], "initial") == raw
    assert not capsys.readouterr().out
    args, kwargs = calls[0]
    assert args[-2:] == ["root@" + client.HOST, "python3 -"]
    assert secrets["control_token"] not in repr(args) + kwargs["input"].decode()


class FakeForward:
    def __init__(self, *_):
        self.api_port, self.control_port, self.birth = 39001, 39002, "owned-child-birth"
        self.proc = SimpleNamespace(pid=1234)
        self.checks = 0
    def check(self):
        self.checks += 1
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False


def receipt(control, request):
    after = {"db-stop": "db-offline", "db-start": "db-recovered",
             "app-restart": "app-restarted", "finish": "finishing"}[request["operation"]]
    value = {**request, "request_sha256": client.digest(request), "details": {},
             "source_manifest_sha256": control.public["source_manifest_sha256"],
             "previous_receipt_sha256": control.previous, "ok": True,
             "before": control.state, "after": after, "completed_scenario": request["seq"] == 4}
    return {**value, "receipt_sha256": client.digest(value)}


def test_control_receipt_chain_and_lost_response_retry_same_identity(session, monkeypatch):
    _, public, secrets, _ = session
    control = client.Control(FakeForward(), public, secrets["control_token"])
    calls = []
    def fake(base, path, **kwargs):
        request = kwargs["body"]
        calls.append(dict(request))
        if len(calls) == 1:
            raise TimeoutError("response lost, execution may have happened")
        return 200, receipt(control, request)
    monkeypatch.setattr(client, "http_json", fake)
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    control.perform("db-stop")
    assert calls[0] == calls[1] and control.seq == 1
    for action in ("db-start", "app-restart", "finish"):
        control.perform(action)
    assert control.finished and len(control.receipts) == 4
    assert control.receipts[-1]["completed_scenario"] is True
    with pytest.raises(client.ClientError):
        control.perform("finish")


@pytest.mark.parametrize("field,value", [("run_id", "f" * 12), ("seq", 9), ("seq", True),
                                        ("schema", True), ("request_sha256", "0"*64),
                                        ("receipt_sha256", "0" * 64),
                                        ("before", "foreign"), ("ok", False)])
def test_control_rejects_forged_receipt_and_no_new_action_after_unknown(session, monkeypatch, field, value):
    _, public, secrets, _ = session
    control = client.Control(FakeForward(), public, secrets["control_token"])
    def fake(base, path, **kwargs):
        result = receipt(control, kwargs["body"])
        result[field] = value
        return 200, result
    monkeypatch.setattr(client, "http_json", fake)
    with pytest.raises(client.ClientError):
        control.perform("db-stop")
    assert control.seq == 0 and control.pending["operation"] == "db-stop"
    with pytest.raises(client.ClientError, match="NOT_ALLOWED"):
        control.perform("finish")


def test_control_status_rejects_foreign_source(session, monkeypatch):
    _, public, secrets, _ = session
    control = client.Control(FakeForward(), public, secrets["control_token"])
    monkeypatch.setattr(client, "http_json", lambda *a, **k: (200, {"schema": 1, "run_id": "f"*12}))
    with pytest.raises(client.ClientError, match="IDENTITY"):
        control.status()


def test_forward_two_local_only_fixed_uds_and_owned_process_cleanup(transport, session, monkeypatch):
    _, public, _, _ = session
    calls = []
    class Process:
        pid = 1234
        stopped = False
        def poll(self):
            return 0 if self.stopped else None
        def terminate(self):
            self.stopped = True
        def wait(self, timeout):
            return 0
    proc = Process()
    monkeypatch.setattr(client.subprocess, "Popen", lambda args, **kw: calls.append(args) or proc)
    monkeypatch.setattr(client, "process_birth", lambda proc: "creation-handle-01")
    with client.Forward(transport[1], public) as owned:
        owned.check()
        assert owned.api_port != owned.control_port
    args = calls[0]
    targets = [args[index+1] for index, item in enumerate(args) if item == "-L"]
    assert len(targets) == 2 and all(item.startswith("127.0.0.1:") for item in targets)
    assert targets[0].endswith(":" + public["api_socket"])
    assert targets[1].endswith(":" + public["control_socket"])
    assert "ClearAllForwardings=no" in args and "ExitOnForwardFailure=yes" in args
    assert "-g" not in args and proc.stopped


def test_forward_does_not_kill_a_replaced_birth(transport, session, monkeypatch):
    _, public, _, _ = session
    forward = client.Forward(transport[1], public)
    forward.proc = SimpleNamespace(poll=lambda: None)
    forward.birth = "original"
    monkeypatch.setattr(client, "process_birth", lambda proc: "foreign")
    with pytest.raises(client.ClientError, match="IDENTITY"):
        forward.__exit__()


def test_command_redaction_and_client_environment_never_forward_local_credentials(tmp_path, session, monkeypatch):
    _, public, secrets, _ = session
    for key in ("POSTGRES_PASSWORD", "PGPASSWORD", "LLM_API_KEY", "WORKSPACE_ACCESS_TOKEN", "HTTP_PROXY"):
        monkeypatch.setenv(key, "production-credential")
    env = client.client_environment(tmp_path, {**public, "api_url": "http://127.0.0.1:39001"}, tmp_path)
    assert "production-credential" not in env.values()
    stdout = ("PASS " + secrets["control_token"] + secrets["mcp_token"]).encode()
    monkeypatch.setattr(client.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout, b""))
    result = client.run_command(["node", "fixed-script"], source=tmp_path, env=env,
                                output=tmp_path, label="probe", secrets=secrets)
    assert result["passed"] and "<QA_SECRET_REDACTED>" in result["stdout"]
    assert secrets["control_token"] not in (tmp_path / "probe.stdout.txt").read_text(encoding="utf-8")


def test_browser_plan_reuses_every_runner_sdk_and_five_phases_without_docker(tmp_path, session, monkeypatch):
    _, public, secrets, _ = session
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/web_regression.js").write_text("__BASE_URL__ __RUN_ID__ __PHASE__", encoding="utf-8")
    public = {**public, "api_url": "http://127.0.0.1:39001"}
    monkeypatch.setattr(client.shutil, "which", lambda name: "/fixed/" + name)
    calls = []
    def fake(command, **kwargs):
        calls.append((command, kwargs["label"], kwargs["env"]))
        return {"passed": True, "exit": 0, "stdout": '{"passed":true}', "stderr": ""}
    monkeypatch.setattr(client, "run_command", fake)
    health = []
    monkeypatch.setattr(client, "_health", lambda base, path, status, **k: health.append((path,status)) or {"passed":True})
    actions = []
    control = SimpleNamespace(perform=lambda action: actions.append(action))
    report = {"checks": []}
    client.run_clients(tmp_path, tmp_path, public, secrets, FakeForward(), control, report)
    labels = [item[1] for item in calls]
    assert all(name.removesuffix(".mjs") in labels for name in client.SCENES)
    assert "mcp-queries" in labels
    assert labels[-7:] == ["phase-open", "phase-core", "phase-prepare-failure",
                           "phase-database-offline", "phase-database-recovered",
                           "phase-application-restarted", "phase-close"]
    assert actions == ["db-stop", "db-start", "app-restart"]
    assert ("/health/ready", 503) in health and ("/api/admin/diagnostics", 200) in health
    sdk = next(item for item in calls if item[1] == "mcp-queries")
    assert sdk[2]["WORKSPACE_MCP_TOKEN"] == secrets["mcp_token"]
    assert all(secrets["control_token"] not in repr(command) + repr(env) for command, _, env in calls)


def test_collect_final_same_run_and_no_secret_files(tmp_path, session, transport, monkeypatch):
    _, public, secrets, _ = session
    value = {"run_id": public["run_id"], "ok": True, "cleaned_owned_cluster": True}
    monkeypatch.setattr(client, "remote_read", lambda *a, **k: {"files": {"result.json": json.dumps(value)}})
    assert client.collect_final(transport[1], tmp_path, public, secrets) == value
    value["run_id"] = "f" * 12
    with pytest.raises(client.ClientError, match="RUN_ID"):
        client.collect_final(transport[1], tmp_path, public, secrets)


def test_nonloopback_or_arbitrary_http_paths_fail_before_network():
    for base, path in (("https://8.156.81.128:8770", "/health/live"),
                       ("http://localhost:39001", "/status"),
                       ("http://127.0.0.1:65536", "/status"),
                       ("http://127.0.0.1:39001", "/api/knowledge")):
        with pytest.raises(client.ClientError):
            client.http_json(base, path)


@pytest.mark.parametrize("server_ok,client_failure,change_source,expected", [
    (True, False, False, True), (False, False, False, False),
    (True, True, False, False), (True, False, True, False),
])
def test_orchestrator_real_acceptance_fields_cleanup_even_on_client_error(
    tmp_path, transport, session, monkeypatch, server_ok, client_failure, change_source, expected
):
    source = tmp_path / "source"; source.mkdir()
    (source / "README.md").write_text("frozen", encoding="ascii")
    manifest = client.source_manifest(source)
    _, public, secrets, raw = session
    public.update({"source_manifest": manifest, "source_manifest_sha256": client.digest(manifest)})
    raw["files"]["session-public.json"] = json.dumps(public)
    result = {"run_id": public["run_id"], "ok": server_ok, "cleaned_owned_cluster": True,
              "pytest_exit": 0, "ruff_exit": 0, "pip_check_exit": 0,
              "source_manifest": manifest, "source_manifest_sha256": client.digest(manifest),
              "completed_scenario": not client_failure}
    reads = []
    def remote(t, mode, **kwargs):
        reads.append(mode)
        return raw if mode == "initial" else {"files": {"result.json": json.dumps(result)}}
    monkeypatch.setattr(client, "remote_read", remote)
    monkeypatch.setattr(client, "Forward", FakeForward)
    controls = []
    original_control = client.Control
    def make_control(*args):
        value = original_control(*args)
        controls.append(value)
        return value
    monkeypatch.setattr(client, "Control", make_control)
    def http(base, path, **kwargs):
        if path == "/__qa__/identity":
            return 200, {"run_id": public["run_id"]}
        if path == "/status":
            return 200, {"schema": 1, "run_id": public["run_id"], "session_id": public["session_id"],
                         "source_manifest_sha256": public["source_manifest_sha256"],
                         "state": "ready", "last_seq": 0, "last_receipt_sha256": client.ZERO,
                         "pending": None}
        return 200, receipt(controls[-1], kwargs["body"])
    monkeypatch.setattr(client, "http_json", http)
    def clients(src, out, pub, sec, forward, control, report):
        if client_failure:
            raise client.ClientError("INJECTED_LOCAL_CLIENT_FAILURE")
        for action in ("db-stop", "db-start", "app-restart"):
            control.perform(action)
        report["checks"].append({"label": "offline orchestrator fixture, not real UI evidence", "passed": True})
        if change_source:
            (source / "README.md").write_text("changed", encoding="ascii")
    monkeypatch.setattr(client, "run_clients", clients)
    output = tmp_path / "evidence"
    value = client.run(transport[0], output, source=source)
    assert value["passed"] is expected
    assert controls[-1].finished and "final" in reads
    assert value["server_result"]["run_id"] == public["run_id"]
    assert "level" not in value
    text = (output / "client-report.json").read_text(encoding="utf-8")
    assert secrets["control_token"] not in text and secrets["mcp_token"] not in text


def test_prepare_wait_polls_only_original_output_then_binds_same_session(transport, session, monkeypatch):
    manifest, public, secrets, raw = session
    calls = []
    def remote(value, mode, **kwargs):
        calls.append((dict(value), mode))
        return {"files": {}} if len(calls) < 3 else raw
    monkeypatch.setattr(client, "remote_read", remote)
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    actual = client.await_session(transport[1], manifest, deadline=client.time.monotonic()+10)
    assert actual == (public, secrets)
    assert calls == [(transport[1], "initial")] * 3


def test_prepare_terminal_or_expired_wait_never_restarts_process(transport, session, monkeypatch):
    manifest, _, _, _ = session
    calls = []
    def remote(*args, **kwargs):
        calls.append(args)
        return {"files": {"result.json": '{"ok":false}'}}
    monkeypatch.setattr(client, "remote_read", remote)
    with pytest.raises(client.ClientError, match="ALREADY_TERMINAL"):
        client.await_session(transport[1], manifest, deadline=client.time.monotonic()+10)
    with pytest.raises(client.ClientError, match="TIMEOUT"):
        client.await_session(transport[1], manifest, deadline=client.time.monotonic()-1)
    assert len(calls) == 1


def test_uncertain_action_cleanup_only_finish_never_repeats_db_operation(session, monkeypatch):
    _, public, secrets, _ = session
    control = client.Control(FakeForward(), public, secrets["control_token"])
    requests = []
    def http(base, path, **kwargs):
        if path == "/status":
            return 200, {"schema": 1, "run_id": public["run_id"], "session_id": public["session_id"],
                         "source_manifest_sha256": public["source_manifest_sha256"], "state": "uncertain",
                         "last_seq": 0, "last_receipt_sha256": client.ZERO, "pending": {"seq": 1}}
        request = kwargs["body"]; requests.append(dict(request))
        if request["operation"] != "finish":
            return 409, {"error": "uncertain"}
        value = {**request, "request_sha256": client.digest(request), "details": {},
                 "before": "uncertain", "after": "finishing", "ok": True,
                 "completed_scenario": False, "source_manifest_sha256": public["source_manifest_sha256"],
                 "previous_receipt_sha256": client.ZERO}
        return 200, {**value, "receipt_sha256": client.digest(value)}
    monkeypatch.setattr(client, "http_json", http)
    with pytest.raises(client.ClientError, match="UNCERTAIN"):
        control.perform("db-stop")
    control.cleanup_only()
    assert [r["operation"] for r in requests] == ["db-stop", "finish"]
    assert control.finished and control.receipts == [] and len(control.cleanup_receipts) == 1
    assert control.cleanup_receipts[0]["completed_scenario"] is False


def test_forward_birth_capture_failure_kills_only_unreaped_owned_child(transport, session, monkeypatch):
    _, public, _, _ = session
    calls = []
    class Child:
        pid = 1234
        alive = True
        def poll(self):
            return None if self.alive else -9
        def terminate(self):
            calls.append("terminate")
        def wait(self, timeout):
            calls.append(("wait", timeout))
            if self.alive:
                raise subprocess.TimeoutExpired("owned SSH fixture", timeout)
        def kill(self):
            calls.append("kill"); self.alive = False
    child = Child()
    monkeypatch.setattr(client.subprocess, "Popen", lambda *a, **kw: child)
    def unavailable(_):
        raise client.ClientError("BIRTH_UNAVAILABLE")
    monkeypatch.setattr(client, "process_birth", unavailable)
    with pytest.raises(client.ClientError, match="BIRTH_UNAVAILABLE"):
        client.Forward(transport[1], public).__enter__()
    assert calls == ["terminate", ("wait", 10), "kill", ("wait", 10)] and not child.alive
