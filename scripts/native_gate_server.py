"""Private Linux UDS session for the unchanged browser/SDK release scenarios.

Only a dedicated owned native-QA process calls this module.  No caller supplies a
command, database endpoint, filesystem path, or PID.  A receipt acknowledges an
owned action; it is not proof that the external browser release gate passed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import psycopg2

OPERATIONS = ("db-stop", "db-start", "app-restart", "finish")
NEXT = {"db-stop": ("ready", "db-offline"),
        "db-start": ("db-offline", "db-recovered"),
        "app-restart": ("db-recovered", "app-restarted")}
FIELDS = {"schema", "run_id", "session_id", "seq", "request_id", "operation"}


class GateSessionError(ValueError):
    """A fixed protocol/ownership failure, never an environment/error dump."""


def canonical(value: dict) -> bytes:
    """Stable bytes for request/receipt hashes; reject nonfinite JSON numbers."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(value: dict) -> str:
    """Return the SHA256 of a canonical object."""
    return hashlib.sha256(canonical(value)).hexdigest()


def _fresh_json(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        if os.name == "posix":
            os.fchmod(stream.fileno(), 0o600)
        else:
            os.chmod(path, 0o600)
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _replace_json(path: Path, value: dict) -> None:
    """Replace only an already private regular file, through a private new inode."""
    old = path.lstat() if os.path.lexists(path) else None
    if old and (not stat.S_ISREG(old.st_mode)
                or (os.name == "posix" and (old.st_mode & 0o077 or old.st_uid != os.geteuid()))):
        raise GateSessionError("Untrusted session state file")
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(6))
    try:
        _fresh_json(temporary, value)
        if old:
            now = path.lstat()
            if (now.st_dev, now.st_ino) != (old.st_dev, old.st_ino):
                raise GateSessionError("Session state identity changed")
        elif os.path.lexists(path):
            raise GateSessionError("Session state publication collided")
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class ControlState:
    """One sequential action ledger with fail-closed uncertain/replay handling."""

    def __init__(self, output: Path, run_id: str, session_id: str,
                 manifest_sha: str, actions: dict[str, Callable[[], dict]]) -> None:
        if (not re.fullmatch(r"[a-f0-9]{12}", run_id)
                or not re.fullmatch(r"[a-f0-9]{32}", session_id)
                or not re.fullmatch(r"[a-f0-9]{64}", manifest_sha)
                or set(actions) != set(OPERATIONS) - {"finish"}):
            raise GateSessionError("Invalid bound controller identity")
        self.output, self.run_id, self.session_id = output, run_id, session_id
        self.manifest_sha, self.actions = manifest_sha, actions
        self.state, self.last_seq, self.last_receipt = "ready", 0, "0" * 64
        self.pending, self.completed_scenario = None, False
        self.lock = threading.Lock()
        self.status_path = output / "gate-status.json"
        if os.path.lexists(self.status_path):
            raise GateSessionError("Controller state already exists")
        self._persist()

    def status(self) -> dict:
        """Return state only; controller tokens and database secrets never appear."""
        return {"schema": 1, "run_id": self.run_id, "session_id": self.session_id,
                "state": self.state, "last_seq": self.last_seq,
                "last_receipt_sha256": self.last_receipt, "pending": self.pending,
                "completed_scenario": self.completed_scenario,
                "source_manifest_sha256": self.manifest_sha}

    def _persist(self) -> None:
        _replace_json(self.status_path, self.status())

    def execute(self, request: dict) -> dict:
        """Never reexecute a completed or uncertain request, even after response loss."""
        if (not isinstance(request, dict) or set(request) != FIELDS
                or type(request.get("schema")) is not int or request["schema"] != 1
                or request.get("run_id") != self.run_id
                or request.get("session_id") != self.session_id
                or type(request.get("seq")) is not int or request["seq"] < 1
                or not isinstance(request.get("request_id"), str)
                or not re.fullmatch(r"[a-f0-9]{32}", request["request_id"])
                or request.get("operation") not in OPERATIONS):
            raise GateSessionError("Invalid control request")
        with self.lock:
            identity = sha(request)
            journal = self.output / ("control-" + request["request_id"] + ".json")
            if os.path.lexists(journal):
                info = journal.lstat()
                if (not stat.S_ISREG(info.st_mode)
                        or (os.name == "posix" and (info.st_mode & 0o077 or info.st_uid != os.geteuid()))):
                    raise GateSessionError("Untrusted request ledger")
                previous = json.loads(journal.read_text(encoding="utf-8"))
                if previous.get("request_sha256") != identity:
                    raise GateSessionError("Request identity was reused")
                if previous.get("status") != "completed":
                    self.state = "uncertain"
                    self._persist()
                    raise GateSessionError("Uncertain action is never repeated")
                receipt = previous["receipt"]
                unsigned = {key: value for key, value in receipt.items()
                            if key != "receipt_sha256"}
                if receipt.get("receipt_sha256") != sha(unsigned):
                    raise GateSessionError("Request receipt changed")
                return receipt
            operation = request["operation"]
            if (request["seq"] != self.last_seq + 1
                    or (self.pending is not None and operation != "finish")
                    or self.state in ("finishing", "finished", "expired")
                    or (operation != "finish" and self.state != NEXT[operation][0])):
                raise GateSessionError("Control operation is out of order")
            before = self.state
            intent = {"status": "intent", "request_sha256": identity,
                      "request": request, "before": before}
            _fresh_json(journal, intent)
            self.pending = {"seq": request["seq"], "request_id": request["request_id"],
                            "operation": operation}
            self._persist()
            try:
                details = {} if operation == "finish" else self.actions[operation]()
                after = "finishing" if operation == "finish" else NEXT[operation][1]
                ok = True
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, psycopg2.Error) as error:
                # Side effects may have happened.  The same action is not retryable.
                details = {"error": "OWNED_GATE_ACTION_FAILED",
                           "reason_code": type(error).__name__}
                after, ok = "uncertain", False
            complete = operation == "finish" and before == "app-restarted" and ok
            receipt = {"schema": 1, "run_id": self.run_id,
                       "session_id": self.session_id, "seq": request["seq"],
                       "request_id": request["request_id"], "operation": operation,
                       "request_sha256": identity, "before": before, "after": after,
                       "ok": ok, "completed_scenario": complete, "details": details,
                       "source_manifest_sha256": self.manifest_sha,
                       "previous_receipt_sha256": self.last_receipt}
            receipt["receipt_sha256"] = sha(receipt)
            try:
                _replace_json(journal, {**intent, "status": "completed", "receipt": receipt})
                self.state, self.last_seq = after, request["seq"]
                self.last_receipt = receipt["receipt_sha256"]
                self.completed_scenario = complete
                self.pending = None
                self._persist()
            except OSError:
                self.state = "uncertain"
                raise
            return receipt


def decode_request(data: bytes) -> dict:
    """Accept one UTF-8 JSON object without duplicate keys or nonfinite values."""
    def unique(pairs: list) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise GateSessionError("Duplicate control request key")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise GateSessionError("Nonfinite control value")

    value = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                       parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise GateSessionError("Control request must be an object")
    return value


def authorized(given: str, token: str, peer_uid: int, owner_uid: int) -> bool:
    """Check both local peer ownership and an in-memory constant-time secret."""
    try:
        encoded = given.encode("ascii")
    except UnicodeEncodeError:
        return False
    return peer_uid in (0, owner_uid) and hmac.compare_digest(encoded, ("Bearer " + token).encode("ascii"))


def _owned_directory(path: Path, uid: int) -> None:
    info = path.lstat()
    if (path.resolve(strict=True) != path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != uid or info.st_mode & 0o077):
        raise GateSessionError("Session directory identity mismatch")


def _socket_identity(path: Path, uid: int) -> tuple[int, int]:
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise GateSessionError("Session socket identity mismatch")
    return info.st_dev, info.st_ino


def _remove_socket(path: Path, uid: int, identity: tuple[int, int] | None) -> None:
    if os.path.lexists(path):
        if identity is None or _socket_identity(path, uid) != identity:
            raise GateSessionError("Refusing to unlink a changed session socket")
        path.unlink()


def _remove_secret(path: Path, uid: int, identity: tuple[int, int] | None,
                   expected_sha: str | None) -> None:
    """Delete only our unchanged private credential inode after both UDS close."""
    if identity is None or not os.path.lexists(path):
        return
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077
            or (info.st_dev, info.st_ino) != identity or info.st_size > 4096):
        raise GateSessionError("Refusing to unlink changed session credentials")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != identity:
            raise GateSessionError("Session credentials changed during cleanup")
        actual = hashlib.sha256(stream.read(4097)).hexdigest()
    current = path.lstat()
    if ((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            or not hmac.compare_digest(actual, expected_sha or "")):
        raise GateSessionError("Session credential contents changed")
    path.unlink()
    _sync_directory(path.parent)


def _browser_configuration(source: Path, root: Path, output: Path) -> dict:
    """Keep base settings but leave QA sentinel and MCP policies fresh for serve."""
    directory = root / "config"
    directory.mkdir(mode=0o700)
    copied = {}
    for original in sorted((source / "config").iterdir()):
        if original.name in ("corpora.yaml", "public-sources.json", "mcp.yaml"):
            continue
        if (original.is_symlink() or not original.is_file()
                or not original.resolve(strict=True).is_relative_to(source)
                or original.suffix not in (".yaml", ".yml", ".json")
                or original.name.startswith(".")):
            raise GateSessionError("Only static base configuration is accepted")
        data = original.read_bytes()
        target = directory / original.name
        shutil.copyfile(original, target)
        target.chmod(0o400)
        if target.read_bytes() != data or original.read_bytes() != data:
            raise GateSessionError("Browser base configuration copy changed")
        copied[original.name] = hashlib.sha256(data).hexdigest()
    _fresh_json(output / "browser-static-config.json", copied)
    return copied


class OwnedApplication:
    """Hold the actual Popen child, not a caller-supplied PID or port."""

    def __init__(self, source: Path, root: Path, output: Path,
                 env: dict, run_id: str, uid: int) -> None:
        self.source, self.root, self.output = source, root, output
        self.env, self.run_id, self.uid = env, run_id, uid
        self.socket = output / "api.sock"
        self.process, self.socket_id, self.log = None, None, None

    def start(self) -> dict:
        """Start a fixed child command and require its exact UDS QA identity."""
        import httpx

        if self.process is not None or os.path.lexists(self.socket):
            raise GateSessionError("App child/socket already exists")
        self.log = (self.output / "gate-app.stdout.txt").open("ab", buffering=0)
        command = [sys.executable, str(self.source / "scripts/ci_verify.py"),
                   "--serve", str(self.root), "--run-id", self.run_id,
                   "--uds", str(self.socket), "--output", str(self.output / "api-command")]
        self.process = subprocess.Popen(command, cwd=self.source, env=self.env,
                                        stdout=self.log, stderr=subprocess.STDOUT,
                                        start_new_session=True, close_fds=True)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise GateSessionError("Owned app exited during startup")
            if self.socket.exists():
                info = self.socket.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != self.uid:
                    raise GateSessionError("Owned app created an invalid socket")
                self.socket.chmod(0o600)
                self.socket_id = _socket_identity(self.socket, self.uid)
                try:
                    with httpx.Client(transport=httpx.HTTPTransport(uds=str(self.socket)),
                                      base_url="http://owned-qa", timeout=3) as client:
                        identity = client.get("/__qa__/identity")
                        if identity.status_code == 200 and identity.json() != {"run_id": self.run_id}:
                            raise GateSessionError("Owned app QA identity mismatch")
                        live, ready = client.get("/health/live"), client.get("/health/ready")
                        if (identity.status_code == live.status_code == ready.status_code == 200
                                and live.json().get("status") == ready.json().get("status") == "ok"):
                            return {"command_id": "owned-api-start", "pid": self.process.pid,
                                    "identity": {"run_id": self.run_id}, "ready_status": 200}
                except httpx.TransportError:
                    pass
            time.sleep(0.2)
        raise GateSessionError("Owned app readiness deadline exceeded")

    def stop(self) -> dict:
        """Confirm actual child exit before reusing its socket or starting again."""
        if self.process is None:
            return {"command_id": "owned-api-stop", "exit_status": None}
        process = self.process
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            result = {"command_id": "owned-api-stop", "pid": process.pid,
                      "exit_status": process.returncode}
            _remove_socket(self.socket, self.uid, self.socket_id)
            self.process, self.socket_id = None, None
            return result
        finally:
            if self.log:
                self.log.close()
                self.log = None

    def restart(self) -> dict:
        """Use the same generated browser data root and new confirmed child."""
        stopped = self.stop()
        started = self.start()
        return {"command_id": "owned-api-restart", "stopped": stopped, "started": started}


def run_session(source: Path, output: Path, cluster_root: Path, env: dict,
                run_id: str, manifest: dict, stop_db: Callable[[], dict],
                start_db: Callable[[], dict], verify_db: Callable[[], dict],
                *, duration: int = 1800) -> dict:
    """Serve a private bounded session and clean its owned API on every exit."""
    if sys.platform != "linux" or os.geteuid() == 0 or not 60 <= duration <= 7200:
        raise GateSessionError("Dedicated Linux QA session required")
    uid = os.geteuid()
    _owned_directory(output, uid)
    _owned_directory(cluster_root, uid)
    if len(os.fsencode(output / "control.sock")) >= 104:
        raise GateSessionError("Session socket path is too long")
    root = cluster_root / "browser-workspace"
    root.mkdir(mode=0o700)
    _owned_directory(root, uid)
    browser_config = _browser_configuration(source, root, output)
    session_id, token, mcp_token = secrets.token_hex(16), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    manifest_sha = sha(manifest)
    app_env = {**env, "PROJECT_ROOT": str(root), "RAG_PROJECT_ROOT": str(root),
               "WEB_RATE_LIMIT_PER_MINUTE": "0", "WORKSPACE_MCP_TOKEN": mcp_token}
    app = OwnedApplication(source, root, output, app_env, run_id, uid)
    controller = None
    control_socket = output / "control.sock"
    secrets_path = output / "session-secrets.json"
    secrets_id, secrets_sha = None, None
    control_id, state = None, None
    try:
        verify_db()
        initial = app.start()

        def restart() -> dict:
            verify_db()
            result = app.restart()
            verify_db()
            return result

        state = ControlState(output, run_id, session_id, manifest_sha,
                             {"db-stop": stop_db, "db-start": start_db, "app-restart": restart})

        class Handler(BaseHTTPRequestHandler):
            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(3)

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _reply(self, code: int, body: dict) -> None:
                data = canonical(body)
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self) -> bool:
                peer = self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                _, peer_uid, _ = struct.unpack("3i", peer)
                given = self.headers.get("Authorization", "")
                if (len(self.headers.get_all("Authorization", [])) != 1
                        or not authorized(given, token, peer_uid, uid)):
                    self._reply(401, {"error": "CONTROL_AUTH_REQUIRED"})
                    return False
                return True

            def do_GET(self) -> None:
                if not self._authorized():
                    return
                if self.path != "/status":
                    self._reply(404, {"error": "CONTROL_ROUTE_NOT_FOUND"})
                    return
                self._reply(200, state.status())

            def do_POST(self) -> None:
                if not self._authorized():
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if (self.path != "/control" or not 0 < size <= 2048
                            or len(self.headers.get_all("Content-Length", [])) != 1
                            or self.headers.get("Content-Type", "") != "application/json"
                            or self.headers.get("Transfer-Encoding")):
                        raise GateSessionError("Invalid bounded controller request")
                    request = decode_request(self.rfile.read(size))
                    receipt = state.execute(request)
                except (GateSessionError, OSError, ValueError, KeyError):
                    self._reply(409, {"error": "CONTROL_REQUEST_REJECTED"})
                    return
                self._reply(200, receipt)

        if os.path.lexists(control_socket):
            raise GateSessionError("Controller socket already exists")
        controller = socketserver.UnixStreamServer(str(control_socket), Handler)
        controller.timeout = 0.5
        control_socket.chmod(0o600)
        control_id = _socket_identity(control_socket, uid)
        created = datetime.now(timezone.utc)
        secret_values = {"schema": 1, "run_id": run_id, "session_id": session_id,
                         "control_token": token, "mcp_token": mcp_token}
        _fresh_json(secrets_path, secret_values)
        secrets_info = secrets_path.lstat()
        secrets_id = (secrets_info.st_dev, secrets_info.st_ino)
        secrets_sha = sha(secret_values)
        _fresh_json(output / "session-public.json", {
            "schema": 1, "kind": "shilie/native-gate-session", "run_id": run_id,
            "uid": uid,
            "session_id": session_id, "source_manifest": manifest,
            "source_manifest_sha256": manifest_sha, "api_socket": str(app.socket),
            "control_socket": str(control_socket), "status_path": str(state.status_path),
            "secrets_path": str(secrets_path), "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "state": "ready", "created_at": created.isoformat(),
            "expires_at": (created + timedelta(seconds=duration)).isoformat(),
        })
        deadline = time.monotonic() + duration
        while state.state != "finishing":
            if time.monotonic() >= deadline:
                state.state = "expired"
                state._persist()
                raise GateSessionError("Native gate session deadline exceeded")
            if app.process is None or app.process.poll() is not None:
                raise GateSessionError("Owned API exited during the gate session")
            controller.handle_request()
        stopped = app.stop()
        for name, expected in browser_config.items():
            original, copied = source / "config" / name, root / "config" / name
            if (copied.is_symlink() or copied.stat().st_mode & 0o222
                    or hashlib.sha256(copied.read_bytes()).hexdigest() != expected
                    or hashlib.sha256(original.read_bytes()).hexdigest() != expected):
                raise GateSessionError("Browser base configuration changed during session")
        state.state = "finished"
        state._persist()
        return {"gate_session_completed": True, "completed_scenario": state.completed_scenario,
                "session_id": session_id, "initial_api": initial, "final_api": stopped,
                "last_receipt_sha256": state.last_receipt,
                "source_manifest_sha256": manifest_sha}
    finally:
        try:
            if controller:
                controller.server_close()
            _remove_socket(control_socket, uid, control_id)
        finally:
            try:
                app.stop()
            finally:
                _remove_secret(secrets_path, uid, secrets_id, secrets_sha)
