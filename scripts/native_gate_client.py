"""Desktop QA clients over temporary pinned SSH-to-Unix-socket forwards.

No Docker, production HTTP requests, remote shell parameters, or arbitrary remote
commands. The operator supplies a narrowly validated transport description; QA
credentials are read through pinned SSH directly into memory, never printed or
passed on a command line. A successful result is evidence for release_gate, not
itself a level=full release report.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from rag_tech_retriever.common.release_manifest import source_manifest

HOST = "8.156.81.128"
HOST_PIN = "SHA256:kf5k4BoDnFNH9oZD/BZCynrBVRfwq9MJWiKPyASx02E"
REMOTE_BASE = "/var/lib/shilie-qa-20261031"
ZERO = "0" * 64
HEX12 = re.compile(r"[a-f0-9]{12}\Z")
HEX32 = re.compile(r"[a-f0-9]{32}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
SCENES = ("verify-ui.mjs", "verify-jobs.mjs", "verify-learning.mjs",
          "verify-job-insights.mjs", "verify-agent-studio.mjs",
          "verify-collaboration.mjs", "verify-public-corpus.mjs")
RECEIPT_FIELDS = {"schema", "run_id", "session_id", "seq", "request_id", "operation",
                  "request_sha256", "before", "after", "ok", "completed_scenario", "details",
                  "source_manifest_sha256", "previous_receipt_sha256", "receipt_sha256"}
FINAL_FILES = ("result.json", "gate-status.json", "workspace-proof.json",
               "workspace-verified.json", "workspace-after-session.json", "ownership-proof.json",
               "pytest-proof.json", "pytest.junit.xml", "browser-static-config.json",
               "pytest.stdout.txt", "pytest.stderr.txt", "pytest.exit.txt",
               "ruff.stdout.txt", "ruff.stderr.txt", "ruff.exit.txt",
               "pip-check.stdout.txt", "pip-check.stderr.txt", "pip-check.exit.txt",
               "static-version.stdout.txt", "static-version.stderr.txt", "static-version.exit.txt",
               "agent-eval.stdout.txt", "agent-eval.stderr.txt", "agent-eval.exit.txt",
               "collaboration-eval.stdout.txt", "collaboration-eval.stderr.txt", "collaboration-eval.exit.txt",
               "agent-contract.json", "collaboration-comparison.json", "gate-app.stdout.txt",
               "gate-db-stop.stdout.txt", "gate-db-stop.stderr.txt", "gate-db-stop.exit.txt",
               "gate-db-start.stdout.txt", "gate-db-start.stderr.txt", "gate-db-start.exit.txt")
CLIENT_TIMEOUT = 3000
PREPARE_TIMEOUT = 1100
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class ClientError(ValueError):
    """Only fixed, credential-free reason codes may escape the client boundary."""


def canonical(value: object) -> bytes:
    """Canonical native JSON bytes used by manifests and the receipt hash chain."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    """Return a stable SHA256 over a JSON value, without printing it."""
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(pairs: list[tuple]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ClientError("DUPLICATE_JSON_FIELD")
        value[key] = item
    return value


def decode(raw: bytes, limit: int = 4 * 1024 * 1024) -> dict:
    """Read bounded UTF8 object JSON, rejecting duplicate keys and non-finite values."""
    if len(raw) > limit:
        raise ClientError("JSON_SIZE_LIMIT")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               ClientError("NONFINITE_JSON")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClientError("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ClientError("JSON_OBJECT_REQUIRED")
    return value


def _regular(path: Path) -> Path:
    if not path.is_absolute():
        raise ClientError("ABSOLUTE_LOCAL_PATH_REQUIRED")
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ClientError("LOCAL_SYMLINK_REJECTED")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ClientError("LOCAL_REGULAR_FILE_REQUIRED")
    return path


def load_transport(path: Path) -> dict:
    """Bind only the previously authorized host, fingerprint and QA output subtree."""
    value = decode(_regular(path.absolute()).read_bytes(), 16 * 1024)
    fields = {"schema", "host", "port", "user", "identity_file", "known_hosts",
              "expected_host_fingerprint", "remote_output"}
    if set(value) != fields or type(value.get("schema")) is not int or value["schema"] != 1:
        raise ClientError("TRANSPORT_SCHEMA_INVALID")
    if (value["host"] != HOST or type(value["port"]) is not int or value["port"] != 22
            or value["user"] != "root" or value["expected_host_fingerprint"] != HOST_PIN):
        raise ClientError("TRANSPORT_AUTHORIZED_TARGET_MISMATCH")
    output = value["remote_output"]
    if (not isinstance(output, str)
            or not re.fullmatch(re.escape(REMOTE_BASE) + r"/[a-z0-9][a-z0-9-]{0,79}", output)
            or str(PurePosixPath(output)) != output):
        raise ClientError("REMOTE_OUTPUT_NOT_ALLOWLISTED")
    for key in ("identity_file", "known_hosts"):
        if not isinstance(value[key], str):
            raise ClientError("LOCAL_FILE_PATH_INVALID")
        _regular(Path(value[key]))
    raw = Path(value["known_hosts"]).read_bytes()
    if len(raw) > 64 * 1024:
        raise ClientError("KNOWN_HOSTS_TOO_LARGE")
    accepted = []
    for line in raw.decode("ascii").splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if len(parts) < 3 or parts[0] not in (HOST, "[" + HOST + "]:22") or parts[1] != "ssh-ed25519":
            raise ClientError("KNOWN_HOSTS_NOT_EXCLUSIVE_PIN")
        try:
            pin = "SHA256:" + base64.b64encode(hashlib.sha256(
                base64.b64decode(parts[2], validate=True)).digest()).decode().rstrip("=")
        except (ValueError, UnicodeError) as exc:
            raise ClientError("KNOWN_HOSTS_KEY_INVALID") from exc
        accepted.append(pin)
    if accepted != [HOST_PIN]:
        raise ClientError("KNOWN_HOSTS_PIN_MISMATCH")
    return value


def ssh_arguments(transport: dict, *, forwards: bool = False) -> list[str]:
    """Ignore user SSH configuration, proxies, agents, password and multiplexing."""
    executable = "C:/Windows/System32/OpenSSH/ssh.exe" if os.name == "nt" else "/usr/bin/ssh"
    options = {"BatchMode": "yes", "IdentitiesOnly": "yes", "IdentityAgent": "none",
               "PasswordAuthentication": "no", "KbdInteractiveAuthentication": "no",
               "StrictHostKeyChecking": "yes", "HostKeyAlgorithms": "ssh-ed25519",
               "KexAlgorithms": "curve25519-sha256", "UserKnownHostsFile": transport["known_hosts"],
               "GlobalKnownHostsFile": "NUL" if os.name == "nt" else "/dev/null",
               "UpdateHostKeys": "no", "ForwardAgent": "no", "ForwardX11": "no",
               "ControlPath": "none", "ControlMaster": "no", "PermitLocalCommand": "no",
               "ProxyCommand": "none", "ProxyJump": "none", "RequestTTY": "no",
               "ConnectTimeout": "20", "ConnectionAttempts": "1",
               "ServerAliveInterval": "15", "ServerAliveCountMax": "3",
               "ClearAllForwardings": "no" if forwards else "yes"}
    args = [executable, "-F", "none", "-T", "-p", "22"]
    for key, value in options.items():
        args.extend(["-o", key + "=" + value])
    return args + ["-i", transport["identity_file"]]


def remote_script(transport: dict, mode: str) -> bytes:
    """A fixed read-only program, not a command/filename supplied by the peer."""
    if mode not in ("initial", "final"):
        raise ClientError("REMOTE_READ_MODE_INVALID")
    # remote_output has a strict ASCII grammar before it reaches this function.
    output = transport["remote_output"]
    if not re.fullmatch(re.escape(REMOTE_BASE) + r"/[a-z0-9][a-z0-9-]{0,79}", output):
        raise ClientError("REMOTE_OUTPUT_NOT_ALLOWLISTED")
    names = ("session-public.json", "session-secrets.json", "result.json") if mode == "initial" else FINAL_FILES
    script = """import json,os,stat
from pathlib import Path
root=Path(__BOUND_OUTPUT__)
for item in (root,*root.parents):
 if item.is_symlink():raise SystemExit('QA_READ_PATH_INVALID')
info=root.stat()
if not stat.S_ISDIR(info.st_mode) or info.st_uid==0 or info.st_mode&0o077:raise SystemExit('QA_READ_OWNER_INVALID')
files={};total=0
for name in __BOUND_NAMES__:
 path=root/name
 if not path.exists():continue
 current=path.lstat()
 if not stat.S_ISREG(current.st_mode) or current.st_uid!=info.st_uid or current.st_mode&0o077 or current.st_size>4*1024*1024:raise SystemExit('QA_READ_FILE_INVALID')
 with os.fdopen(os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)),'rb') as stream:
  if (os.fstat(stream.fileno()).st_dev,os.fstat(stream.fileno()).st_ino)!=(current.st_dev,current.st_ino):raise SystemExit('QA_READ_FILE_CHANGED')
  raw=stream.read(4*1024*1024+1)
 if len(raw)>4*1024*1024:raise SystemExit('QA_READ_TOO_LARGE')
 total+=len(raw)
 if total>8*1024*1024:raise SystemExit('QA_READ_TOTAL_TOO_LARGE')
 after=path.lstat()
 if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns):raise SystemExit('QA_READ_FILE_CHANGED')
 files[name]=raw.decode('utf-8')
if 'session-secrets.json' in files and 'session-public.json' in files and 'result.json' not in files:
 for name in ('api.sock','control.sock'):
  current=(root/name).lstat()
  if not stat.S_ISSOCK(current.st_mode) or current.st_uid!=info.st_uid or current.st_mode&0o077:raise SystemExit('QA_READ_SOCKET_INVALID')
payload=json.dumps({'uid':info.st_uid,'files':files},ensure_ascii=False)
if len(payload.encode('utf-8'))>12*1024*1024:raise SystemExit('QA_READ_OUTPUT_TOO_LARGE')
print(payload)
"""
    return script.replace("__BOUND_OUTPUT__", repr(output)).replace("__BOUND_NAMES__", repr(names)).encode("utf-8")


def remote_read(transport: dict, mode: str, *, timeout: float = 45) -> dict:
    """Keep the initial secret-bearing stdout in this process's memory only."""
    command = ssh_arguments(transport) + ["root@" + HOST, "python3 -"]
    try:
        ran = subprocess.run(command, input=remote_script(transport, mode), capture_output=True,
                             timeout=min(45, timeout), check=False, **HIDDEN)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClientError("PINNED_REMOTE_READ_UNAVAILABLE") from exc
    if ran.returncode:
        raise ClientError("PINNED_REMOTE_READ_FAILED")
    return decode(ran.stdout, 24 * 1024 * 1024)


def await_session(transport: dict, manifest: dict, *, deadline: float) -> tuple[dict, dict]:
    """Poll only the operator-bound output while its original pytest run completes."""
    deadline = min(deadline, time.monotonic() + PREPARE_TIMEOUT)
    while time.monotonic() < deadline:
        try:
            raw = remote_read(transport, "initial", timeout=max(1, deadline-time.monotonic()))
        except ClientError as exc:
            if str(exc) not in ("PINNED_REMOTE_READ_FAILED", "PINNED_REMOTE_READ_UNAVAILABLE"):
                raise
        else:
            files = raw.get("files", {})
            if not isinstance(files, dict):
                raise ClientError("SESSION_FORMAT_INVALID")
            if "result.json" in files:
                raise ClientError("ORIGINAL_QA_ALREADY_TERMINAL_NO_SESSION_RESTART")
            if "session-public.json" in files and "session-secrets.json" in files:
                return validate_session(raw, transport, manifest)
        time.sleep(min(5, max(0, deadline-time.monotonic())))
    raise ClientError("ORIGINAL_QA_PREPARE_OBSERVATION_TIMEOUT")


def validate_session(raw: dict, transport: dict, manifest: dict) -> tuple[dict, dict]:
    """Bind run/source/expiry and fixed UDS paths before starting a forward."""
    try:
        public = decode(raw["files"]["session-public.json"].encode(), 2 * 1024 * 1024)
        secrets = decode(raw["files"]["session-secrets.json"].encode(), 4096)
        output = transport["remote_output"]
        if (type(public["schema"]) is not int or public["schema"] != 1
                or public["kind"] != "shilie/native-gate-session"
                or not HEX12.fullmatch(public["run_id"])
                or not HEX32.fullmatch(public["session_id"])
                or public["source_manifest"] != manifest
                or public["source_manifest_sha256"] != digest(manifest)
                or public["state"] != "ready"
                or type(raw["uid"]) is not int or raw["uid"] <= 0
                or public.get("uid") != raw["uid"]):
            raise ClientError("SESSION_BINDING_INVALID")
        for field, name in (("api_socket", "api.sock"), ("control_socket", "control.sock"),
                            ("status_path", "gate-status.json"), ("secrets_path", "session-secrets.json")):
            if public[field] != output + "/" + name:
                raise ClientError("SESSION_FIXED_PATH_MISMATCH")
        created = datetime.fromisoformat(public["created_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(public["expires_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if (created.utcoffset() is None or expires.utcoffset() is None
                or not 0 < (expires - created).total_seconds() <= 1800
                or (created - now).total_seconds() > 30 or now >= expires):
            raise ClientError("SESSION_EXPIRED_OR_CLOCK_INVALID")
        if (set(secrets) != {"schema", "run_id", "session_id", "control_token", "mcp_token"}
                or type(secrets["schema"]) is not int or secrets["schema"] != 1
                or secrets["run_id"] != public["run_id"]
                or secrets["session_id"] != public["session_id"]):
            raise ClientError("SESSION_SECRET_IDENTITY_MISMATCH")
        for key in ("control_token", "mcp_token"):
            if not isinstance(secrets[key], str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", secrets[key]):
                raise ClientError("SESSION_TOKEN_INVALID")
        if (secrets["control_token"] == secrets["mcp_token"]
                or public["token_sha256"] != hashlib.sha256(secrets["control_token"].encode()).hexdigest()):
            raise ClientError("SESSION_TOKEN_PIN_MISMATCH")
        return public, secrets
    except (KeyError, TypeError, OverflowError, ValueError) as exc:
        if isinstance(exc, ClientError):
            raise
        raise ClientError("SESSION_FORMAT_INVALID") from exc


def process_birth(proc: subprocess.Popen) -> str:
    """Observe the SSH child by an OS creation identity, not a reusable PID alone."""
    if proc.poll() is not None:
        raise ClientError("FORWARD_PROCESS_NOT_LIVE")
    if os.name == "nt":
        from ctypes import wintypes

        values = [wintypes.FILETIME() for _ in range(4)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        if not kernel.GetProcessTimes(wintypes.HANDLE(int(proc._handle)), *map(ctypes.byref, values)):
            raise ClientError("FORWARD_BIRTH_UNAVAILABLE")
        return "windows:" + str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
    raw = Path(f"/proc/{proc.pid}/stat").read_text(encoding="ascii")
    birth = raw[raw.rfind(")") + 2:].split()[19]
    boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    return "linux:" + boot + ":" + birth


class Forward:
    """Own one SSH process and two loopback-only Unix-socket forwards."""

    def __init__(self, transport: dict, public: dict):
        self.transport, self.public = transport, public
        self.proc = None
        self.birth = ""
        with socket.socket() as first, socket.socket() as second:
            first.bind(("127.0.0.1", 0)); second.bind(("127.0.0.1", 0))
            self.api_port, self.control_port = first.getsockname()[1], second.getsockname()[1]

    def __enter__(self):
        args = ssh_arguments(self.transport, forwards=True)
        args += ["-N", "-o", "ExitOnForwardFailure=yes", "-L",
                 f"127.0.0.1:{self.api_port}:{self.public['api_socket']}", "-L",
                 f"127.0.0.1:{self.control_port}:{self.public['control_socket']}", "root@" + HOST]
        self.command = args
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, **HIDDEN)
        try:
            self.birth = process_birth(self.proc)
        except BaseException:
            # An unreaped child cannot have its PID recycled; Windows Popen also
            # holds its creation handle. Do not leak a just-created SSH child.
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=10)
            raise
        return self

    def check(self) -> None:
        """Refuse a dead/replaced forward before every session action."""
        if self.proc is None or process_birth(self.proc) != self.birth:
            raise ClientError("FORWARD_PROCESS_IDENTITY_MISMATCH")

    def __exit__(self, *_):
        if self.proc is not None and self.proc.poll() is None:
            # Do not signal an identity that is no longer the child we observed.
            self.check()
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.check(); self.proc.kill(); self.proc.wait(timeout=10)


def http_json(base: str, path: str, *, token: str = "", body: dict | None = None,
              timeout: int = 15) -> tuple[int, dict]:
    """No proxy, redirects or arbitrary host: only our temporary loopback HTTP ports."""
    if not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", base):
        raise ClientError("NONLOOPBACK_HTTP_REJECTED")
    if not 1 <= int(base.rsplit(":", 1)[1]) <= 65535:
        raise ClientError("HTTP_PORT_INVALID")
    if path not in ("/status", "/control", "/__qa__/identity", "/health/live", "/health/ready",
                    "/api/admin/diagnostics"):
        raise ClientError("HTTP_PATH_NOT_ALLOWLISTED")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            raise ClientError("HTTP_REDIRECT_REJECTED")

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base + path, data=canonical(body) if body is not None else None,
                                     headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, decode(response.read(2 * 1024 * 1024 + 1), 2 * 1024 * 1024)


class Control:
    """Strict request identity/replay and receipt-chain validation for a live session."""

    def __init__(self, forward: Forward, public: dict, token: str):
        self.forward, self.public, self.token = forward, public, token
        self.base = "http://127.0.0.1:" + str(forward.control_port)
        self.seq, self.previous = 0, ZERO
        self.receipts = []
        self.finished = False
        self.state = "ready"
        self.pending = None
        self.cleanup_receipts = []

    def status(self) -> dict:
        """Read without consuming a sequence number or accepting another run."""
        self.forward.check()
        code, value = http_json(self.base, "/status", token=self.token)
        if (code != 200 or type(value.get("schema")) is not int or value.get("schema") != 1
                or value.get("run_id") != self.public["run_id"]
                or value.get("session_id") != self.public["session_id"]
                or value.get("source_manifest_sha256") != self.public["source_manifest_sha256"]):
            raise ClientError("CONTROL_STATUS_IDENTITY_INVALID")
        return value

    def verify_receipt(self, receipt: dict, request: dict) -> None:
        """Validate all identity/order fields and hash, then advance exactly once."""
        if (set(receipt) != RECEIPT_FIELDS or type(receipt.get("schema")) is not int
                or type(receipt.get("seq")) is not int
                or receipt.get("request_sha256") != digest(request)
                or type(request.get("seq")) is not int or request["seq"] != self.seq + 1):
            raise ClientError("CONTROL_RECEIPT_SEQUENCE_INVALID")
        for key in ("schema", "run_id", "session_id", "seq", "request_id", "operation"):
            if receipt.get(key) != request[key]:
                raise ClientError("CONTROL_RECEIPT_REQUEST_MISMATCH")
        hashed = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        if (receipt.get("source_manifest_sha256") != self.public["source_manifest_sha256"]
                or receipt.get("previous_receipt_sha256") != self.previous
                or receipt.get("receipt_sha256") != digest(hashed)
                or receipt.get("ok") is not True):
            raise ClientError("CONTROL_RECEIPT_INVALID_OR_FAILED")
        expected = {"db-stop": "db-offline", "db-start": "db-recovered",
                    "app-restart": "app-restarted", "finish": "finishing"}
        if receipt.get("before") != self.state or receipt.get("after") != expected[request["operation"]]:
            raise ClientError("CONTROL_TRANSITION_INVALID")
        self.seq = request["seq"]
        self.previous = receipt["receipt_sha256"]
        self.receipts.append(receipt)
        self.state = receipt["after"]
        self.pending = None

    def perform(self, operation: str) -> dict:
        """A lost response retries the identical request, never a new operation identity."""
        if (operation not in ("db-stop", "db-start", "app-restart", "finish")
                or self.finished or self.pending is not None):
            raise ClientError("CONTROL_OPERATION_NOT_ALLOWED")
        request = {"schema": 1, "run_id": self.public["run_id"],
                   "session_id": self.public["session_id"], "seq": self.seq + 1,
                   "request_id": uuid4().hex, "operation": operation}
        self.pending = request
        bound = self.public.get("_finish_deadline" if operation == "finish" else "_client_deadline",
                                time.monotonic() + 95)
        deadline = min(bound, time.monotonic() + 95)
        while time.monotonic() < deadline:
            self.forward.check()
            try:
                code, receipt = http_json(self.base, "/control", token=self.token,
                                           body=request, timeout=max(1, min(70, int(deadline-time.monotonic()))))
                if code == 200:
                    self.verify_receipt(receipt, request)
                    self.finished = operation == "finish"
                    return receipt
                if code not in (202, 409):
                    raise ClientError("CONTROL_REQUEST_REJECTED")
                status = self.status()
                if status.get("state") in ("unknown", "uncertain", "expired", "failed", "finished"):
                    raise ClientError("CONTROL_UNCERTAIN_OR_TERMINAL")
            except (OSError, urllib.error.URLError):
                # Observation loss is not proof of terminal state or safe repetition
                # with another identity. Server replay returns the original receipt.
                pass
            time.sleep(1)
        raise ClientError("CONTROL_OBSERVATION_TIMEOUT")

    def cleanup_only(self) -> None:
        """Finish an uncertain failed session; never retry its DB/app operation.

        This independent cleanup receipt is deliberately NOT accepted into the
        successful scenario chain. The original failure remains a gate failure.
        """
        state = self.status()
        if state.get("state") in ("finished", "expired", "finishing"):
            return
        if (type(state.get("last_seq")) is not int or state["last_seq"] < self.seq
                or not isinstance(state.get("last_receipt_sha256"), str)
                or not HEX64.fullmatch(state["last_receipt_sha256"])
                or state.get("state") not in ("ready", "db-offline", "db-recovered", "app-restarted", "uncertain")):
            raise ClientError("CLEANUP_STATUS_INVALID")
        request = {"schema": 1, "run_id": self.public["run_id"], "session_id": self.public["session_id"],
                   "seq": state["last_seq"] + 1, "request_id": uuid4().hex, "operation": "finish"}
        self.forward.check()
        remaining = self.public.get("_finish_deadline", time.monotonic()+70) - time.monotonic()
        code, receipt = http_json(self.base, "/control", token=self.token, body=request,
                                  timeout=max(1, min(70, int(remaining))))
        unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        if (code != 200 or set(receipt) != RECEIPT_FIELDS
                or type(receipt.get("schema")) is not int or type(receipt.get("seq")) is not int
                or receipt.get("request_sha256") != digest(request)
                or any(receipt.get(key) != value for key, value in request.items())
                or receipt.get("receipt_sha256") != digest(unsigned) or receipt.get("ok") is not True
                or receipt.get("before") != state["state"] or receipt.get("after") != "finishing"
                or receipt.get("previous_receipt_sha256") != state["last_receipt_sha256"]
                or receipt.get("source_manifest_sha256") != self.public["source_manifest_sha256"]):
            raise ClientError("CLEANUP_RECEIPT_INVALID")
        self.cleanup_receipts.append(receipt)
        self.finished = True


def client_environment(source: Path, public: dict, output: Path) -> dict:
    """Do not send local database/production credentials to a browser or SDK."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PG", "POSTGRES_", "SHILIE_QA_", "LLM_", "WORKSPACE_"))
           and key.casefold() not in ("http_proxy", "https_proxy", "all_proxy")}
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(source / "src"),
                "WEB_QA_URL": public["api_url"] + "/", "WEB_QA_RUN_ID": public["run_id"],
                "WEB_QA_OUTPUT": str(output), "NO_PROXY": "127.0.0.1,localhost"})
    return env


def run_command(command: list[str], *, source: Path, env: dict, output: Path,
                label: str, secrets: dict, timeout: int = 180) -> dict:
    """Record literal outputs/exits, redacting only the two ephemeral credentials."""
    try:
        ran = subprocess.run(command, cwd=source, env=env, capture_output=True,
                             timeout=timeout, check=False, **HIDDEN)
        code, stdout, stderr = ran.returncode, ran.stdout, ran.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = 124, exc.stdout or b"", exc.stderr or b""
    except OSError:
        code, stdout, stderr = 127, b"", b"CLIENT_EXECUTABLE_UNAVAILABLE"
    def clean(raw: bytes) -> str:
        value = raw.decode("utf-8", "replace")
        for key in ("control_token", "mcp_token"):
            value = value.replace(secrets[key], "<QA_SECRET_REDACTED>")
        return value
    result = {"label": label, "command": command, "exit": code,
              "stdout": clean(stdout), "stderr": clean(stderr)}
    for name in ("stdout", "stderr"):
        (output / (label + "." + name + ".txt")).write_text(result[name], encoding="utf-8")
    (output / (label + ".exit.txt")).write_text(str(code), encoding="ascii")
    if code or "### Error" in result["stdout"] or "✗" in result["stdout"]:
        result["passed"] = False
    else:
        result["passed"] = True
    return result


def _health(api: str, path: str, status: int, *, diagnostics: bool = False) -> dict:
    code, value = http_json(api, path, timeout=15)
    if code != status or (status == 200 and (
            value.get("passed") is not True or not value.get("checks")
            if diagnostics else value.get("status") != "ok")):
        raise ClientError("HEALTH_OR_DIAGNOSTICS_ASSERTION_FAILED")
    return {"path": path, "status": code, "body": value, "passed": True}


def run_clients(source: Path, output: Path, public: dict, secrets: dict,
                forward: Forward, control: Control, report: dict) -> None:
    """Run the existing seven UI runners, SDK and five persistent browser phases."""
    node = shutil.which("node")
    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    if not node or not npx:
        raise ClientError("NODE_OR_OFFLINE_PLAYWRIGHT_CLI_UNAVAILABLE")
    env = client_environment(source, public, output)
    checks = report["checks"]
    def command(args: list[str], label: str, command_env: dict | None = None) -> None:
        forward.check()
        remaining = public.get("_client_deadline", time.monotonic() + 180) - time.monotonic()
        if remaining <= 1:
            raise ClientError("CLIENT_SESSION_DEADLINE")
        value = run_command(args, source=source, env=command_env or env, output=output,
                            label=label, secrets=secrets, timeout=min(180, int(remaining)))
        checks.append(value)
        if not value["passed"]:
            raise ClientError("CLIENT_COMMAND_FAILED")
    for scene in SCENES:
        args = [node, str(source / "scripts" / scene)] + (["all"] if scene == "verify-ui.mjs" else [])
        command(args, scene.removesuffix(".mjs"))
    command([sys.executable, str(source / "scripts/verify_mcp_queries.py")], "mcp-queries",
            {**env, "WORKSPACE_MCP_TOKEN": secrets["mcp_token"]})
    checks.extend([_health(public["api_url"], "/health/live", 200),
                   _health(public["api_url"], "/health/ready", 200),
                   _health(public["api_url"], "/api/admin/diagnostics", 200, diagnostics=True)])
    cli = [npx, "--offline", "--registry=https://registry.npmjs.org", "--yes",
           "--package", "@playwright/cli@0.1.22", "playwright-cli", "-s=qa" + public["run_id"]]
    opened = False
    try:
        command(cli + ["open", public["api_url"] + "/#module/knowledge", "--browser", "chrome"], "phase-open")
        opened = True
        def phase(name: str) -> None:
            script = (source / "scripts/web_regression.js").read_text(encoding="utf-8")
            script = script.replace("__BASE_URL__", json.dumps(public["api_url"])).replace(
                "__RUN_ID__", json.dumps(public["run_id"])).replace("__PHASE__", json.dumps(name))
            path = output / (name + ".js")
            path.write_text(script, encoding="utf-8")
            command(cli + ["run-code", "--filename", str(path)], "phase-" + name)
            if '"passed":true' not in checks[-1]["stdout"]:
                raise ClientError("BROWSER_PHASE_RESULT_MISSING")
        phase("core"); phase("prepare-failure")
        control.perform("db-stop")
        phase("database-offline")
        checks.extend([_health(public["api_url"], "/health/live", 200),
                       _health(public["api_url"], "/health/ready", 503)])
        control.perform("db-start")
        phase("database-recovered")
        control.perform("app-restart")
        phase("application-restarted")
        checks.append(_health(public["api_url"], "/health/ready", 200))
    finally:
        if opened:
            result = run_command(cli + ["close"], source=source, env=env, output=output,
                                 label="phase-close", secrets=secrets, timeout=25)
            checks.append(result)


def collect_final(transport: dict, output: Path, public: dict, secrets: dict) -> dict:
    """Observe the same session's terminal result/cleanup without restarting it."""
    deadline = min(public.get("_finish_deadline", time.monotonic()+100), time.monotonic()+100)
    last_error = "SERVER_RESULT_NOT_TERMINAL"
    while time.monotonic() < deadline:
        try:
            raw = remote_read(transport, "final", timeout=max(1, deadline-time.monotonic()))
            files = raw.get("files", {})
            if "result.json" in files:
                value = decode(files["result.json"].encode())
                if value.get("run_id") != public["run_id"]:
                    raise ClientError("SERVER_FINAL_RUN_ID_MISMATCH")
                for name, text in files.items():
                    if name not in FINAL_FILES or not isinstance(text, str):
                        raise ClientError("SERVER_FINAL_FILE_NOT_ALLOWLISTED")
                    for key in ("control_token", "mcp_token"):
                        text = text.replace(secrets[key], "<QA_SECRET_REDACTED>")
                    (output / ("server-" + name)).write_text(text, encoding="utf-8")
                return value
        except ClientError as exc:
            last_error = str(exc)
            if last_error == "SERVER_FINAL_RUN_ID_MISMATCH":
                raise
        time.sleep(2)
    raise ClientError(last_error)


def run(session_path: Path, output: Path, *, source: Path = PROJECT) -> dict:
    """Execute one real native QA client session and always attempt bounded cleanup."""
    source = source.resolve(strict=True)
    deadline = time.monotonic() + CLIENT_TIMEOUT
    manifest = source_manifest(source)
    transport = load_transport(session_path)
    if output.exists() or output.is_symlink():
        raise ClientError("FRESH_OUTPUT_REQUIRED")
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    report = {"schema": 1, "kind": "shilie/native-gate-client", "passed": False,
              "source_manifest": manifest, "source_manifest_sha256": digest(manifest),
              "checks": [], "receipts": [], "production_used": False, "docker_used": False}
    public = secrets = control = None
    try:
        public, secrets = await_session(transport, manifest, deadline=deadline-150)
        report.update({"run_id": public["run_id"], "session_id": public["session_id"],
                       "remote_output": transport["remote_output"]})
        with Forward(transport, public) as forward:
            remaining = (datetime.fromisoformat(public["expires_at"].replace("Z", "+00:00"))
                         - datetime.now(timezone.utc)).total_seconds()
            public = {**public, "api_url": "http://127.0.0.1:" + str(forward.api_port),
                      "_client_deadline": min(deadline-150, time.monotonic()+remaining-150),
                      "_finish_deadline": min(deadline, time.monotonic()+remaining-10)}
            control = Control(forward, public, secrets["control_token"])
            deadline = time.monotonic() + 30
            while True:
                try:
                    state = control.status()
                    code, identity = http_json(public["api_url"], "/__qa__/identity")
                    if (state.get("state") != "ready" or type(state.get("last_seq")) is not int
                            or state.get("last_seq") != 0
                            or state.get("last_receipt_sha256") != ZERO or state.get("pending") is not None
                            or code != 200 or identity != {"run_id": public["run_id"]}):
                        raise ClientError("SESSION_ALREADY_USED_OR_IDENTITY_INVALID")
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise ClientError("FORWARD_NOT_READY")
                    time.sleep(.3)
            report["transport_process"] = {"pid": forward.proc.pid, "birth": forward.birth,
                                            "command": getattr(forward, "command", []),
                                            "local_only": True, "remote_tcp_opened": False}
            try:
                run_clients(source, output, public, secrets, forward, control, report)
            finally:
                try:
                    if not control.finished:
                        if control.pending is None:
                            control.perform("finish")
                        else:
                            control.cleanup_only()
                finally:
                    report["receipts"] = list(control.receipts)
                    report["cleanup_receipts"] = list(control.cleanup_receipts)
        report["transport_process"]["exit"] = getattr(forward.proc, "returncode", None)
        report["transport_process"]["closed_by_client"] = True
        report["server_result"] = collect_final(transport, output, public, secrets)
        server = report["server_result"]
        if (server.get("ok") is not True or server.get("cleaned_owned_cluster") is not True
                or any(type(server.get(name)) is not int or server[name] != 0
                       for name in ("pytest_exit", "ruff_exit", "pip_check_exit"))
                or server.get("source_manifest") != manifest
                or server.get("source_manifest_sha256") != digest(manifest)
                or server.get("completed_scenario") is not True
                or not control.finished or not control.receipts[-1].get("completed_scenario")
                or any(check.get("passed") is not True for check in report["checks"])):
            raise ClientError("SERVER_OR_CLIENT_ACCEPTANCE_INCOMPLETE")
        if source_manifest(source) != manifest:
            raise ClientError("LOCAL_SOURCE_CHANGED_DURING_NATIVE_GATE")
        report["passed"] = True
    except (ClientError, OSError, ValueError, KeyError) as exc:
        report["failure"] = str(exc) if isinstance(exc, ClientError) else "CLIENT_OPERATION_FAILED"
    finally:
        if public and secrets and "server_result" not in report:
            try:
                report["server_result"] = collect_final(transport, output, public, secrets)
            except (ClientError, OSError, ValueError):
                report["server_result_observation"] = "UNAVAILABLE_NOT_A_RESTART_PERMISSION"
        try:
            report["source_unchanged"] = source_manifest(source) == manifest
        except (OSError, ValueError):
            report["source_unchanged"] = False
        if not report["source_unchanged"]:
            report["passed"] = False
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        if secrets:
            for key in ("control_token", "mcp_token"):
                encoded = encoded.replace(secrets[key], "<QA_SECRET_REDACTED>")
        (output / "client-report.json").write_text(encoded, encoding="utf-8")
    return report


def main() -> int:
    """Only an explicit operator-bound session and a fresh evidence directory are accepted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.session, args.output)
        print("NATIVE_GATE_CLIENT_PASS" if result["passed"] else "NATIVE_GATE_CLIENT_FAILED")
        return 0 if result["passed"] else 1
    except (ClientError, OSError, ValueError, KeyError):
        print("NATIVE_GATE_CLIENT_BLOCKED: invalid session, transport or output", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
