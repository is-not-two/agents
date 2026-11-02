"""Run browser regression against a disposable PostgreSQL container, never the user's DB.

Usage: .venv/Scripts/python.exe scripts/web_regression.py
Prerequisites: Docker, Chrome, and cached @playwright/cli 0.1.22 (see README).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
CLI_PACKAGE = "@playwright/cli@0.1.22"
IMAGE = "pgvector/pgvector:pg16"


def command(args: list[str], **kwargs) -> str:
    """Execute without a shell; do not echo command arguments or credentials."""
    result = subprocess.run(args, check=False, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=kwargs.pop("timeout", 120),
                            **HIDDEN, **kwargs)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-2500:])
    return result.stdout


def request(base: str, path: str) -> dict:
    """Read local QA identity/health only."""
    with urllib.request.urlopen(base + path, timeout=2) as response:
        return json.load(response)


def wait_ready(base: str, run_id: str, proc: subprocess.Popen, timeout: int = 60) -> None:
    """Refuse browser automation unless this is our isolated server."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("Isolated API exited during startup")
        try:
            if request(base, "/__qa__/identity") != {"run_id": run_id}:
                raise RuntimeError("QA identity mismatch: refusing browser automation")
            if request(base, "/health")["status"] == "ok":
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(.3)
    raise RuntimeError("Isolated PostgreSQL/API did not become ready")


def serve(root: Path, run_id: str, port: int) -> None:
    """Child process uses private temp files and a unique record table prefix."""
    import uvicorn

    from rag_tech_retriever.api.main import create_app
    from rag_tech_retriever.api.routes import private
    from rag_tech_retriever.platform.record_store import RecordStore

    private._meta_path = lambda _: root / "test-vault.json"
    app = create_app(RecordStore("qa_web_" + run_id), root=root, token="")

    @app.get("/__qa__/identity")
    def identity() -> dict:
        return {"run_id": run_id}

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


def run() -> None:
    """Own and clean all test processes/volumes, including after a failed assertion."""
    docker = shutil.which("docker")
    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    if not docker or not npx:
        raise RuntimeError("Docker and Node/npm are required")
    command([docker, "info", "--format", "{{.ServerVersion}}"], timeout=15)
    run_id = uuid4().hex[:12]
    container = "shilie-qa-" + run_id
    session = "qa" + run_id
    proc = None
    launched_browser = False
    with tempfile.TemporaryDirectory(prefix="shilie-regression-") as temp:
        root = Path(temp)
        base_cli = [npx, "--offline", "--registry=https://registry.npmjs.org", "--yes",
                    "--package", CLI_PACKAGE, "playwright-cli", "-s=" + session]
        try:
            # Bind a specific free host port. Docker can reassign an automatic
            # ephemeral port when the container is stopped and started again.
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                db_port = sock.getsockname()[1]
            command([docker, "run", "-d", "--name", container,
                     "--label", "io.shilie.regression=" + run_id,
                     "-p", f"127.0.0.1:{db_port}:5432", "-e", "POSTGRES_DB=regression",
                     "-e", "POSTGRES_USER=regression", "-e",
                     "POSTGRES_PASSWORD=" + (password := secrets.token_urlsafe(18)), IMAGE])
            env = {**os.environ, "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(db_port),
                   "POSTGRES_DB": "regression", "POSTGRES_USER": "regression",
                   "POSTGRES_PASSWORD": password, "WORKSPACE_REQUIRE_AUTH": "false",
                   "LLM_API_KEY": "", "PYTHONIOENCODING": "utf-8",
                   # 回归含密集页面加载与故障注入重试，关闭限流避免测试自身触发 429。
                   "WEB_RATE_LIMIT_PER_MINUTE": "0"}
            # Wait for the new container, not for the existing production server.
            for _ in range(60):
                try:
                    command([docker, "exec", container, "pg_isready", "-U", "regression"], timeout=5)
                    break
                except RuntimeError:
                    time.sleep(.5)
            else:
                raise RuntimeError("Disposable PostgreSQL startup failed")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}"

            def start() -> subprocess.Popen:
                return subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--serve", str(root),
                     "--run-id", run_id, "--port", str(port)], cwd=PROJECT, env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN,
                )

            proc = start()
            wait_ready(base, run_id, proc)
            launched_browser = True
            opened = command(base_cli + ["open", base + "/#module/knowledge", "--browser", "chrome"], cwd=root)
            if "### Error" in opened:
                raise RuntimeError(opened[-1500:])

            def browser(phase: str) -> None:
                script = (PROJECT / "scripts/web_regression.js").read_text(encoding="utf-8")
                script = script.replace("__BASE_URL__", json.dumps(base)).replace(
                    "__RUN_ID__", json.dumps(run_id)).replace("__PHASE__", json.dumps(phase))
                path = root / "phase.js"
                path.write_text(script, encoding="utf-8")
                output = command(base_cli + ["run-code", "--filename", str(path)], cwd=root)
                if "### Error" in output or '"passed":true' not in output:
                    raise RuntimeError(output[-2200:])
                print("PASS", phase, flush=True)

            browser("core")
            browser("prepare-failure")
            command([docker, "stop", "--time", "5", container])
            browser("database-offline")
            command([docker, "start", container])
            wait_ready(base, run_id, proc)
            browser("database-recovered")
            proc.terminate()
            proc.wait(timeout=10)
            proc = start()
            wait_ready(base, run_id, proc)
            browser("application-restarted")
            print("PASS: browser checks and real isolated database/application restarts", flush=True)
        finally:
            if launched_browser:
                try:
                    command(base_cli + ["close"], cwd=root, timeout=20)
                except (RuntimeError, subprocess.TimeoutExpired):
                    pass
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
            # Delete only a container whose random name AND ownership label match this run.
            try:
                owner = command([docker, "inspect", "--format",
                                 '{{index .Config.Labels "io.shilie.regression"}}', container]).strip()
                if owner == run_id:
                    command([docker, "rm", "-f", "-v", container])
            except RuntimeError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.serve:
            serve(args.serve, args.run_id, args.port)
        else:
            run()
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print("FAIL:", error, file=sys.stderr)
        sys.exit(1)
