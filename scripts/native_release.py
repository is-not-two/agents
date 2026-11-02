"""Explicit, local-only native releases; no shell, package installation or database migration."""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
import re
import secrets
import select
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

SCHEMA = 1
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_FILES = 10000
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
SOURCE_ROOTS = {"src", "config", "scripts", "tests", "docs", ".github"}
SOURCE_FILES = {"pyproject.toml", "requirements.txt", "README.md", "Dockerfile", "docker-compose.yml",
                ".env.example", ".gitignore", "data/processed/agent_golden_set.json", "data/processed/collaboration_tasks.json"}


class ReleaseError(Exception):
    """Safe public failure: never include child output or environment values."""


def digest(path: Path) -> str:
    """Hash a regular local file without loading an archive into memory."""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ReleaseError("duplicate JSON key")
        result[key] = value
    return result


def _json(data: bytes) -> dict:
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise ReleaseError("JSON object required")
    return value


def _write(path: Path, value: dict, *, replace: bool = False) -> None:
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    if not replace:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8))
    _write(temporary, value)
    os.replace(temporary, path)
    _sync(path.parent)


def _sync(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _plain(path: Path) -> Path:
    """Reject symbolic links/junctions at every component, including parent paths."""
    path = Path(os.path.abspath(path))
    for part in reversed((path, *path.parents)):
        if os.path.lexists(part):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ReleaseError("unmanaged symlink/reparse point")
    return path


def _name(value: str) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value) or value in {".", ".."}:
        raise ReleaseError("invalid release/runtime identity")
    return value


def _root(root: Path, expected: Path) -> Path:
    root, expected = _plain(root), _plain(expected)
    if root != expected or not root.is_dir():
        raise ReleaseError("expected project root mismatch")
    info = root.stat()
    if os.name != "nt" and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise ReleaseError("managed root must be owned and not group/world writable")
    marker = _json(_plain(root / "NATIVE-INSTALLATION.json").read_bytes())
    if marker != {"schema": SCHEMA, "project_root": str(root)}:
        raise ReleaseError("installation marker mismatch")
    for name in ("releases", "inbox", "runtimes", "shared"):
        if not _plain(root / name).is_dir():
            raise ReleaseError("managed directory missing")
    return root


def initialize(root: Path, expected: Path) -> dict:
    """Bootstrap a dedicated empty installation directory, never an existing checkout."""
    root, expected = _plain(root), _plain(expected)
    if root != expected:
        raise ReleaseError("expected project root mismatch")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ReleaseError("initialization requires an empty dedicated directory")
    for name in ("releases", "inbox", "runtimes", "shared"):
        (root / name).mkdir(mode=0o700)
    _write(root / "NATIVE-INSTALLATION.json", {"schema": SCHEMA, "project_root": str(root)})
    return {"initialized": True, "project_root": str(root)}


@contextlib.contextmanager
def locked(root: Path):
    """One operation at a time; stale locks require explicit operator diagnosis, never guessing."""
    lock = root / ".native-release.lock"
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    own = os.fstat(descriptor)
    try:
        os.write(descriptor, json.dumps({"pid": os.getpid()}).encode())
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        now = lock.lstat()
        if (now.st_dev, now.st_ino) == (own.st_dev, own.st_ino):
            lock.unlink()


def register_runtime(root: Path, expected: Path, runtime_id: str, python: Path, runner_sha256: str,
                     site_packages: Path | None = None) -> dict:
    """Approve only a Python interpreter and a pinned managed runner, not arbitrary argv."""
    root = _root(root, expected)
    runtime_id = _name(runtime_id)
    runner = _plain(root / "runtimes" / runtime_id / "runner.py")
    python = Path(os.path.abspath(python))
    if not re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)*)?(?:\.exe)?", python.name, re.IGNORECASE):
        raise ReleaseError("only an explicitly approved Python interpreter is supported")
    if not runner.is_file() or not python.is_file() or digest(runner) != runner_sha256:
        raise ReleaseError("runner/interpreter approval mismatch")
    if os.name == "nt" and (python.parent.parent / "pyvenv.cfg").exists():
        raise ReleaseError("Windows venv redirectors are unsupported; explicitly approve base Python and dependency directory")
    sites = str(_plain(site_packages)) if site_packages is not None else ""
    if sites and not Path(sites).is_dir():
        raise ReleaseError("approved dependency directory missing")
    with locked(root):
        _write(runner.parent / "APPROVED.json", {"python": str(python), "python_sha256": digest(python),
                                               "runner_sha256": runner_sha256, "site_packages": sites})
    return {"runtime_approved": runtime_id}


def _runtime(root: Path, runtime_id: str) -> tuple[Path, Path, str]:
    directory = _plain(root / "runtimes" / _name(runtime_id))
    policy = _json(_plain(directory / "APPROVED.json").read_bytes())
    runner = _plain(directory / "runner.py")
    python = Path(policy["python"])
    if (not python.is_absolute() or not python.is_file() or digest(python) != policy["python_sha256"]
            or not runner.is_file() or digest(runner) != policy["runner_sha256"]):
        raise ReleaseError("approved interpreter/runner changed")
    sites = policy.get("site_packages", "")
    if sites and not _plain(Path(sites)).is_dir():
        raise ReleaseError("approved dependency directory missing")
    return python, runner, sites


def _source_name(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or "\x00" in name or name != path.as_posix()
            or path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/"))
            or any(part.endswith((".", " ")) for part in path.parts)
            or any(part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *("COM"+str(i) for i in range(1,10)), *("LPT"+str(i) for i in range(1,10))} for part in path.parts)):
        raise ReleaseError("unsafe archive path")
    if name != "RELEASE-MANIFEST.json" and name not in SOURCE_FILES and path.parts[0] not in SOURCE_ROOTS:
        raise ReleaseError("archive contains non-source data")
    if any(part in {".env", "__pycache__", "_archived"} for part in path.parts):
        raise ReleaseError("archive contains private/generated data")
    return name


def _manifest(value: dict) -> dict:
    if not value or len(value) > MAX_FILES:
        raise ReleaseError("invalid source manifest")
    for name, sha in value.items():
        if _source_name(name) == "RELEASE-MANIFEST.json" or not isinstance(sha, str) or not DIGEST.fullmatch(sha):
            raise ReleaseError("invalid source manifest entry")
    return value


def _source_sha(manifest: dict) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def stage(root: Path, expected: Path, release_id: str, runtime_id: str, bundle: Path,
          gate: Path, expected_sha256: str) -> dict:
    """Validate the exact gate/ZIP/SHA tuple before creating a never-overwritten release."""
    root = _root(root, expected)
    release_id = _name(release_id)
    _runtime(root, runtime_id)
    with locked(root):
        bundle, gate = _plain(bundle), _plain(gate)
        if any(not p.is_relative_to(root / "inbox") or not p.is_file() for p in (bundle, gate)):
            raise ReleaseError("inputs must be regular files in managed inbox")
        if any(character in bundle.name for character in "\r\n"):
            raise ReleaseError("ambiguous archive filename")
        checksum = _plain(bundle.with_suffix(bundle.suffix + ".sha256"))
        if (not DIGEST.fullmatch(expected_sha256) or bundle.stat().st_size > MAX_ARCHIVE
                or digest(bundle) != expected_sha256
                or checksum.read_text(encoding="utf-8") != expected_sha256 + "  " + bundle.name + "\n"):
            raise ReleaseError("archive/SHA mismatch or oversized archive")
        report = _json(gate.read_bytes())
        if report.get("schema") != 1 or report.get("level") != "full" or report.get("passed") is not True:
            raise ReleaseError("source gate is not full/passed")
        with zipfile.ZipFile(bundle) as archive:
            entries = archive.infolist()
            names = [_source_name(item.filename) for item in entries]
            if (len(entries) > MAX_FILES + 1 or len({name.casefold() for name in names}) != len(names)
                    or sum(item.file_size for item in entries) > MAX_EXPANDED):
                raise ReleaseError("duplicate or oversized archive")
            for item in entries:
                mode = item.external_attr >> 16
                if (item.is_dir() or (stat.S_IFMT(mode) not in {0, stat.S_IFREG}) or item.flag_bits & 1
                        or item.file_size > MAX_FILE or item.file_size > max(item.compress_size, 1) * 200):
                    raise ReleaseError("nonregular, encrypted or bomb archive entry")
            manifest = _manifest(_json(archive.read("RELEASE-MANIFEST.json")))
            if set(names) != set(manifest) | {"RELEASE-MANIFEST.json"} or report.get("source_manifest") != manifest:
                raise ReleaseError("source gate/manifest mismatch")
            # Read bounded members and verify CRC+hash before publishing any release files.
            contents = {name: archive.read(name) for name in manifest}
            if any(hashlib.sha256(contents[name]).hexdigest() != sha for name, sha in manifest.items()):
                raise ReleaseError("source file SHA mismatch")
        target = root / "releases" / release_id
        target.mkdir(mode=0o700)  # Exclusive: failed/incomplete identities are never reused.
        (target / "INCOMPLETE").write_text("not activatable\n", encoding="ascii")
        for name, data in contents.items():
            path = target.joinpath(*PurePosixPath(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(data)
        _write(target / "RELEASE-MANIFEST.json", manifest)
        metadata = {"release_id": release_id, "runtime_id": runtime_id, "source_sha256": _source_sha(manifest),
                    "archive_sha256": expected_sha256, "gate_sha256": digest(gate)}
        _write(target / "NATIVE-RELEASE.json", metadata)
        (target / "INCOMPLETE").unlink()
        _sync(target)
        return {"staged": True, **metadata}


def _release(root: Path, release_id: str) -> dict:
    directory = _plain(root / "releases" / _name(release_id))
    if os.path.lexists(directory / "INCOMPLETE"):
        raise ReleaseError("incomplete release")
    metadata = _json(_plain(directory / "NATIVE-RELEASE.json").read_bytes())
    manifest = _manifest(_json(_plain(directory / "RELEASE-MANIFEST.json").read_bytes()))
    if metadata.get("release_id") != release_id or metadata.get("source_sha256") != _source_sha(manifest):
        raise ReleaseError("release identity mismatch")
    seen = set()
    for path in directory.rglob("*"):
        _plain(path)
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            if name not in {"NATIVE-RELEASE.json", "RELEASE-MANIFEST.json"}:
                seen.add(name)
                if name not in manifest or digest(path) != manifest[name]:
                    raise ReleaseError("staged source changed")
    if seen != set(manifest):
        raise ReleaseError("staged source missing")
    _runtime(root, metadata["runtime_id"])
    return metadata


def _pointer(root: Path, name: str) -> str:
    if name not in {"current", "previous"}:
        raise ReleaseError("invalid release pointer name")
    # A regular JSON file can be atomically replaced on both Windows and POSIX;
    # directory symlinks cannot be replaced equivalently on Windows.
    path = root / (name + ".json")
    if os.path.lexists(root / name):
        raise ReleaseError("legacy/unmanaged pointer path is not supported")
    if not os.path.lexists(path):
        return "NONE"
    path = _plain(path)
    if not path.is_file() or path.stat().st_size > 1024:
        raise ReleaseError("pointer must be a bounded regular JSON file")
    value = _json(path.read_bytes())
    release_id = _name(value.get("release_id"))
    if type(value.get("schema")) is not int or value != {"schema": SCHEMA, "release_id": release_id}:
        raise ReleaseError("release pointer schema mismatch")
    _release(root, release_id)
    return release_id


def _switch(root: Path, name: str, release_id: str) -> None:
    _pointer(root, name)  # Reject unknown files/reparse points rather than overwrite them.
    path = root / (name + ".json")
    if release_id == "NONE":
        path.unlink(missing_ok=True)
        _sync(root)
        return
    _release(root, release_id)
    _write(path, {"schema": SCHEMA, "release_id": release_id}, replace=True)


def _argv(root: Path, release_id: str, action: str, nonce: str, port: int) -> list[str]:
    metadata = _release(root, release_id)
    python, runner, sites = _runtime(root, metadata["runtime_id"])
    return [str(python), "-B", "-I", str(runner), action, "--release-root", str(root / "releases" / release_id),
            "--shared-root", str(root / "shared"), "--release-id", release_id,
            "--source-sha256", metadata["source_sha256"], "--nonce", nonce, "--port", str(port),
            "--site-packages", sites]


def _env() -> dict:
    # Credentials may be inherited by the actual application, never printed/recorded.
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "RAG_PROJECT_ROOT", "PROJECT_ROOT"):
        env.pop(name, None)
    env.update(WORKSPACE_PROFILE="production", WORKSPACE_SCHEMA_MODE="verify", PYTHONDONTWRITEBYTECODE="1")
    return env


def _get(port: int, path: str) -> dict:
    # No proxy or redirects: a remote/stale server must not satisfy release identity.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    request = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with request.open(f"http://127.0.0.1:{port}" + path, timeout=0.5) as response:
        if response.status != 200:
            raise ReleaseError("health status not ready")
        return _json(response.read(16385))


def _process_identity(root: Path, state: dict) -> bool:
    try:
        return (not _exited(state) and _get(state["port"], "/health/release") == {
                    "release_id": state["release_id"], "source_sha256": _release(root, state["release_id"])["source_sha256"],
                    "nonce": state["nonce"], "pid": state["pid"]})
    except (OSError, ValueError, ReleaseError, KeyError):
        return False


def _identity(root: Path, state: dict) -> bool:
    try:
        return _process_identity(root, state) and _get(state["port"], "/health/ready").get("status") == "ok"
    except (OSError, ValueError, ReleaseError, KeyError):
        return False


def _wait(root: Path, state: dict, timeout: float, process: subprocess.Popen | None = None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise ReleaseError("candidate exited before ready")
        if _identity(root, state):
            return
        time.sleep(0.05)
    raise ReleaseError("bounded readiness/identity check failed")


def _start(root: Path, release_id: str, port: int) -> tuple[subprocess.Popen, dict]:
    nonce = secrets.token_hex(24)
    process = subprocess.Popen(_argv(root, release_id, "serve", nonce, port), cwd=root / "shared", env=_env(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               shell=False, start_new_session=os.name != "nt")
    try:
        birth = _birth(process.pid)
        if birth is None:
            raise ReleaseError("candidate exited during launch")
        return process, {"release_id": release_id, "port": port, "nonce": nonce, "pid": process.pid, "birth": birth}
    except BaseException:
        _kill_own(process, 3)
        raise


def _windows_handle(pid: int):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p, *([ctypes.c_void_p] * 4)]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    handle = kernel.OpenProcess(0x1000 | 0x100000 | 0x1, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return kernel, None
        raise ReleaseError("cannot establish OS process identity")
    return kernel, handle


def _windows_birth(kernel, handle) -> str:
    times = [ctypes.c_ulonglong() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
        raise ReleaseError("cannot read OS process birth")
    return str(times[0].value)


def _birth(pid: int) -> str | None:
    if os.name == "nt":
        kernel, handle = _windows_handle(pid)
        if handle is None:
            return None
        try:
            if kernel.WaitForSingleObject(handle, 0) == 0:
                return None
            return _windows_birth(kernel, handle)
        finally:
            kernel.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return None if fields[0] == "Z" else fields[19]
        except FileNotFoundError:
            return None
    raise ReleaseError("OS process lifetime verification unsupported on this platform")


def _exited(state: dict) -> bool:
    if not isinstance(state.get("birth"), str) or type(state.get("pid")) is not int:
        raise ReleaseError("missing durable OS process identity")
    return _birth(state["pid"]) != state["birth"]


def _stop(root: Path, state: dict, timeout: float) -> None:
    # Never signal an unverified/reused PID. No arbitrary process-group or service commands.
    if not _process_identity(root, state):
        raise ReleaseError("refusing to signal a process without exact live identity")
    if os.name == "nt":
        kernel, handle = _windows_handle(state["pid"])
        if handle is None:
            return
        try:
            if _windows_birth(kernel, handle) != state["birth"]:
                raise ReleaseError("refusing to signal reused PID")
            if not kernel.TerminateProcess(handle, 0):
                raise ReleaseError("OS process stop failed")
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise ReleaseError("process exit timeout; endpoint loss is not process exit")
        finally:
            kernel.CloseHandle(handle)
    elif sys.platform.startswith("linux") and hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        descriptor = os.pidfd_open(state["pid"])
        try:
            if _birth(state["pid"]) != state["birth"]:
                raise ReleaseError("refusing to signal reused PID")
            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
            poll = select.poll(); poll.register(descriptor, select.POLLIN)
            if not poll.poll(int(timeout * 1000)):
                raise ReleaseError("process exit timeout; endpoint loss is not process exit")
        finally:
            os.close(descriptor)
    else:
        raise ReleaseError("safe process stop unsupported on this platform")


def _kill_own(process: subprocess.Popen, timeout: float) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)


def activate(root: Path, expected: Path, release_id: str, expected_current: str, *, port: int,
             schema_compatible: bool, timeout: float = 15, preflight_timeout: float = 30,
             rollback_timeout: float = 30) -> dict:
    """Preflight -> atomic pointer -> real process -> exact ready; compensate on failures/signals."""
    root = _root(root, expected)
    release_id = _name(release_id)
    if (not schema_compatible or type(port) is not int or not 1024 <= port <= 65535
            or not 0.2 <= timeout <= 120 or not 0.2 <= preflight_timeout <= 300
            or not 0.2 <= rollback_timeout <= 120):
        raise ReleaseError("explicit schema compatibility, unprivileged port and bounded timeouts required")
    with locked(root):
        if os.path.lexists(root / "PENDING.json"):
            raise ReleaseError("unfinished operation requires explicit recover")
        old = _pointer(root, "current")
        if old != expected_current or old == release_id:
            raise ReleaseError("expected current identity mismatch/no-op")
        _release(root, release_id)
        old_state = _json(_plain(root / "RUNNING.json").read_bytes()) if old != "NONE" else None
        if old_state and (old_state.get("release_id") != old or old_state.get("port") != port or not _identity(root, old_state)):
            raise ReleaseError("previous process is not the expected healthy identity")
        try:
            checked = subprocess.run(_argv(root, release_id, "preflight", "preflight", port), cwd=root / "shared", env=_env(),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     shell=False, timeout=preflight_timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ReleaseError("preflight timeout; current untouched") from exc
        if checked.returncode != 0:
            codes = {b"NATIVE_APP_NOT_READY_APPLICATION", b"NATIVE_APP_NOT_READY_DEPENDENCY",
                     b"NATIVE_APP_NOT_READY_LIFESPAN", b"NATIVE_APP_NOT_READY_SERVE"}
            code = checked.stderr.strip() if checked.stderr and len(checked.stderr) <= 128 else b""
            safe_code = code.decode("ascii") if code in codes else "NATIVE_PREFLIGHT_FAILED"
            raise ReleaseError("preflight failed (" + safe_code + "); current untouched")
        pending = {"old": old, "new": release_id, "old_state": old_state, "port": port,
                   "rollback_timeout": rollback_timeout,
                   "candidate_state": None, "launch_intent": False}
        _write(root / "PENDING.json", pending)
        candidate = None
        try:
            _switch(root, "previous", old)
            _switch(root, "current", release_id)
            if old_state:
                _stop(root, old_state, timeout)
            pending["launch_intent"] = True
            _write(root / "PENDING.json", pending, replace=True)
            candidate, state = _start(root, release_id, port)
            pending["candidate_state"] = state
            _write(root / "PENDING.json", pending, replace=True)
            _wait(root, state, timeout, candidate)
            _write(root / "RUNNING.json", state, replace=True)
            (root / "PENDING.json").unlink()
            return {"activated": True, "from": old, "current": release_id, "previous": old,
                    "identity_verified": True, "pid": state["pid"], "preflight_exit": checked.returncode}
        except BaseException as failure:
            if candidate is not None:
                _kill_own(candidate, rollback_timeout)
            try:
                restored = _restore(root, pending, rollback_timeout)
            except BaseException as rollback:
                raise ReleaseError("activation failed; recovery incomplete; PENDING retained for operator") from rollback
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            return {"activated": False, "from": old, "failed": release_id, "current": old,
                    "previous_ready": restored, "preflight_exit": checked.returncode}


def _restore(root: Path, pending: dict, timeout: float) -> bool:
    # Even a first bootstrap can have an unrecorded, not-yet-listening child.
    # Pointer/port observations cannot prove that such a process does not exist.
    candidate = pending.get("candidate_state")
    if pending.get("launch_intent") and not candidate:
        raise ReleaseError("uncertain launch journal gap; PENDING retained for operator")
    if candidate and not _exited(candidate):
        raise ReleaseError("candidate has not exited; refusing restoration over a live process")
    old = pending["old"]
    _switch(root, "current", old)
    if old == "NONE":
        (root / "RUNNING.json").unlink(missing_ok=True)
        (root / "PENDING.json").unlink()
        return False
    old_state = pending.get("restored_state") or pending["old_state"]
    if pending.get("restore_launch_intent") and not pending.get("restored_state"):
        raise ReleaseError("uncertain previous-process launch journal gap; PENDING retained for operator")
    if not _process_identity(root, old_state):
        if not _exited(old_state):
            raise ReleaseError("previous process still exists without verified endpoint; refusing duplicate start")
        pending["restore_launch_intent"] = True
        pending["restored_state"] = None
        _write(root / "PENDING.json", pending, replace=True)
        process, old_state = _start(root, old, pending["port"])
        try:
            pending["restored_state"] = old_state
            _write(root / "PENDING.json", pending, replace=True)
            _wait(root, old_state, timeout, process)
        except BaseException:
            _kill_own(process, timeout)
            raise
    _wait(root, old_state, timeout)
    _write(root / "RUNNING.json", old_state, replace=True)
    (root / "PENDING.json").unlink()
    return True


def recover(root: Path, expected: Path, expected_current: str, timeout: float = 15) -> dict:
    """Explicit compensation after a crash; stale locks remain an operator responsibility."""
    root = _root(root, expected)
    if not 0.2 <= timeout <= 120:
        raise ReleaseError("bounded recovery timeout required")
    with locked(root):
        if _pointer(root, "current") != expected_current:
            raise ReleaseError("recovery expected current mismatch")
        pending = _json(_plain(root / "PENDING.json").read_bytes())
        if expected_current not in {pending["old"], pending["new"]}:
            raise ReleaseError("recovery journal mismatch")
        candidate = pending.get("candidate_state")
        if pending.get("launch_intent") and not candidate:
            raise ReleaseError("uncertain launch journal gap; operator must identify any process before recovery")
        if candidate:
            if _process_identity(root, candidate):
                _stop(root, candidate, timeout)
            elif not _exited(candidate):
                raise ReleaseError("candidate exists without health identity; refusing unknown process signal")
        ready = _restore(root, pending, timeout)
        return {"recovered": True, "current": pending["old"], "previous_ready": ready}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "approve-runtime", "stage", "activate", "recover"])
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--expected-project-root", type=Path, required=True)
    parser.add_argument("--release-id")
    parser.add_argument("--runtime-id")
    parser.add_argument("--python", type=Path)
    parser.add_argument("--runner-sha256")
    parser.add_argument("--site-packages", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--gate", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-current")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--schema-compatible", action="store_true")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--preflight-timeout", type=float, default=30)
    parser.add_argument("--rollback-timeout", type=float, default=30)
    args = parser.parse_args()
    try:
        positional = (args.project_root, args.expected_project_root)
        if args.action == "init":
            result = initialize(*positional)
        elif args.action == "approve-runtime":
            result = register_runtime(*positional, args.runtime_id, args.python, args.runner_sha256, args.site_packages)
        elif args.action == "stage":
            result = stage(*positional, args.release_id, args.runtime_id, args.bundle, args.gate, args.expected_sha256)
        elif args.action == "recover":
            result = recover(*positional, args.expected_current, args.timeout)
        else:
            result = activate(*positional, args.release_id, args.expected_current, port=args.port,
                              schema_compatible=args.schema_compatible, timeout=args.timeout,
                              preflight_timeout=args.preflight_timeout, rollback_timeout=args.rollback_timeout)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("activated", True) else 1
    except (OSError, ValueError, TypeError, KeyError, ReleaseError, zipfile.BadZipFile):
        print("NATIVE_RELEASE_BLOCKED: inspect trusted inputs, identities, journal and permissions", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
