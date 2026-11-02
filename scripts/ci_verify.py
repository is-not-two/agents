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
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import psycopg2

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "output/ci/isolated"
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
CLI_PACKAGE = "@playwright/cli@0.1.22"
# Immutable cached/QA-tested digest, not a mutable major-version tag.
IMAGE = "pgvector/pgvector@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a"


def command(args: list[str], **kwargs) -> str:
    """Execute without a shell; do not echo command arguments or credentials."""
    result = subprocess.run(args, check=False, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=kwargs.pop("timeout", 120),
                            **HIDDEN, **kwargs)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-2500:])
    return result.stdout


def request(base: str, path: str, timeout: float = 2) -> dict:
    """Read local QA identity/health only."""
    with urllib.request.urlopen(base + path, timeout=timeout) as response:
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


def serve(root: Path, run_id: str, port: int | None = None, *, uds: Path | None = None) -> None:
    """Child process uses private temp files and a unique record table prefix."""
    import uvicorn

    from rag_tech_retriever.api.routes import private
    from rag_tech_retriever.platform.record_store import RecordStore

    # Real, isolated corpus files, not route mocks or semantic-quality fixtures.
    # Keep them stable over this run's application restart.
    if not (root / "config/corpora.yaml").exists():
        import yaml

        from rag_tech_retriever.platform.corpus_catalog import DEFAULT
        from rag_tech_retriever.platform.public_corpus import bundle, fingerprint, write_fresh

        policy = {**DEFAULT, "allowed": ["tech_doc", "public_docs"]}
        (root / "config").mkdir(exist_ok=True)
        (root / "config/corpora.yaml").write_text(yaml.safe_dump(policy, allow_unicode=True), encoding="utf-8")
        private_path = root / policy["corpora"]["tech_doc"]["path"]
        private_path.parent.mkdir(parents=True, exist_ok=True)
        private_path.write_text(json.dumps({"chunk_id": "shared", "source_file": "qa-private.md", "heading_path": "PRIVATE_ONLY",
            "content": "PRIVATE_ONLY isolated file sentinel", "meta": {"status_marker": "UNKNOWN"}}) + "\n", encoding="utf-8")
        rows = [{"chunk_id": "shared", "source_file": "qa-public.md", "heading_path": "PUBLIC_ONLY persistence",
                 "content": 'PUBLIC_ONLY checkpointer <img src=x onerror=alert(1)>', "status_marker": "UNKNOWN"}]
        approval = {"schema": 1, "embedding": {"model": "fixture-not-semantic", "dim": 4},
                    "sources": {"qa-public.md": {"url": "https://docs.langchain.com/fixture", "license": "test-only"}},
                    "chunk_hashes": {row["chunk_id"]: fingerprint(row) for row in rows}}
        (root / "config/public-sources.json").write_text(json.dumps(approval), encoding="utf-8")
        write_fresh(root / policy["corpora"]["public_docs"]["path"], bundle(rows, approval))

    private._meta_path = lambda _: root / "test-vault.json"
    import yaml

    from rag_tech_retriever.api.routes import mcp as mcp_routes
    from rag_tech_retriever.common.config_loader import ConfigLoader
    from rag_tech_retriever.platform.mcp_policy import BUSINESS_TOOLS

    mcp_path = root / "config/mcp.yaml"
    if not mcp_path.exists():
        policy = ConfigLoader(PROJECT / "config/mcp.yaml").get("tools")
        for name in BUSINESS_TOOLS: policy[name]["enabled"] = True
        mcp_path.write_text(yaml.safe_dump({"server": {"name": "owned-qa-readonly"}, "tools": policy,
            "permissions": {"readonly": True, "admin": False}, "resources": {"corpus": {"enabled": False}}}), encoding="utf-8")
    mcp_routes._load_mcp_config = lambda: ConfigLoader(mcp_path)
    # Importing main constructs its default app as well. Prepare the isolated
    # corpus/MCP policy first so a fresh native browser root is complete.
    from rag_tech_retriever.api.main import create_app

    app = create_app(RecordStore("qa_web_" + run_id), root=root, token="")

    @app.get("/__qa__/identity")
    def identity() -> dict:
        return {"run_id": run_id}

    @app.get("/__qa__/mcp/readonly-fingerprint")
    def readonly_fingerprint() -> dict:
        import hashlib
        assert os.environ.get("SHILIE_QA_RUN_ID") == run_id
        store = app.state.store
        with store.transaction() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(f"SELECT * FROM {store.records} ORDER BY id"); records = cur.fetchall()
            cur.execute(f"SELECT * FROM {store.versions} ORDER BY record_id,version"); versions = cur.fetchall()
        return {"sha256": hashlib.sha256(json.dumps([records, versions], default=str, sort_keys=True).encode()).hexdigest(),
                "records": len(records), "versions": len(versions)}

    @app.post("/__qa__/notifications/fail-before-data")
    def notification_transport_failure() -> dict:
        # QA-only fault injection against an owned loopback socket: no external
        # recipients, no message DATA, no production route or arbitrary target.
        import threading

        from rag_tech_retriever.platform.notifications import NotificationService

        if os.environ.get("SHILIE_QA_RUN_ID") != run_id:
            raise RuntimeError("Owned QA identity required")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(10)

            def disconnect() -> None:
                peer, _ = listener.accept()
                peer.close()

            thread = threading.Thread(target=disconnect, daemon=True)
            thread.start()
            values = {"NOTIFY_ENABLED": "true", "SMTP_SECURITY": "local-test", "SMTP_HOST": "127.0.0.1",
                      "SMTP_PORT": str(listener.getsockname()[1]), "SMTP_FROM": "qa-sender@example.com", "SMTP_TO": "qa-recipient@example.com"}
            result = NotificationService(app.state.store, env=lambda key, default="": values.get(key, default)).dispatch(1)
            thread.join(timeout=3)
            return result

    if uds is not None:
        # A private native gate uses an owned filesystem socket, never a QA TCP
        # listener on the host. The operator must arrange authenticated transport.
        if (os.environ.get("SHILIE_QA_RUN_ID") != run_id or not uds.is_absolute()
                or uds.parent.resolve(strict=True) != uds.parent
                or os.path.lexists(uds) or len(os.fsencode(uds)) > 100):
            raise RuntimeError("Invalid owned native QA socket")
        uvicorn.run(app, uds=str(uds), log_level="error")
    else:
        if port is None or not 1 <= port <= 65535:
            raise RuntimeError("Explicit QA port required")
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
    server_log = (EVIDENCE / "server.stdout.txt").open("ab")
    launched_browser = False
    with tempfile.TemporaryDirectory(prefix="shilie-regression-") as temp:
        root = Path(temp).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve() and root.name.startswith("shilie-regression-")
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
                   "WORKSPACE_PROFILE": "local", "WORKSPACE_ACCESS_TOKEN": "",
                   "WORKSPACE_SCHEMA_MODE": "",
                   "WORKSPACE_MCP_TOKEN": "",
                   # 回归含密集页面加载与故障注入重试，关闭限流避免测试自身触发 429。
                   "WEB_RATE_LIMIT_PER_MINUTE": "0"}
            # Wait for the new container, not for the existing production server.
            for _ in range(60):
                try:
                    command([docker, "exec", container, "pg_isready", "-h", "127.0.0.1",
                             "-p", "5432", "-U", "regression", "-d", "regression"], timeout=5)
                    # An initdb temporary server may accept Unix socket probes.
                    # Also verify the exact authenticated host path used by tests.
                    with closing(psycopg2.connect(host="127.0.0.1", port=db_port, dbname="regression",
                            user="regression", password=password, connect_timeout=1,
                            options="-c statement_timeout=1000")) as ready, ready.cursor() as cur:
                        cur.execute("SELECT current_database(), current_user")
                        if cur.fetchone() != ("regression", "regression"):
                            raise ValueError("Disposable database identity mismatch")
                    break
                except (RuntimeError, psycopg2.OperationalError):
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
                    stdout=server_log, stderr=subprocess.STDOUT, **HIDDEN,
                )

            # Run full tests only against the disposable database configured above.
            env["SHILIE_QA_RUN_ID"] = run_id
            seed = command([sys.executable, str(PROJECT / "scripts/seed_ci_corpus.py"), run_id],
                           cwd=PROJECT, env=env)
            (EVIDENCE / "seed.stdout.txt").write_text(seed, encoding="utf-8")
            print(seed, flush=True)
            # Full-suite assertions require default rate-limit settings; only browser
            # stress/recovery scenarios disable the limiter in their own server env.
            test_env = {**env, "WEB_RATE_LIMIT_PER_MINUTE": "120"}
            test = subprocess.run([sys.executable, "-m", "pytest", "-q", "--basetemp", str(root / "pytest-tmp")], check=False, cwd=PROJECT,
                                  env=test_env, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=300, **HIDDEN)
            (EVIDENCE / "pytest.stdout.txt").write_text(test.stdout, encoding="utf-8")
            (EVIDENCE / "pytest.stderr.txt").write_text(test.stderr, encoding="utf-8")
            (EVIDENCE / "pytest.exit.txt").write_text(str(test.returncode), encoding="utf-8")
            print(test.stdout, flush=True)
            if test.returncode:
                raise RuntimeError("Full pytest failed on disposable PostgreSQL; see pytest logs")

            env["WORKSPACE_MCP_TOKEN"] = secrets.token_urlsafe(32)
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

            # The same portable scene runner is used locally and on hosted CI.
            images = EVIDENCE / "browser-artifacts"
            images.mkdir(exist_ok=True)
            browser_env = {**env, "WEB_QA_URL": base + "/", "WEB_QA_OUTPUT": str(images), "WEB_QA_RUN_ID": run_id}
            checked = subprocess.run(["node", str(PROJECT / "scripts/verify-ui.mjs"), "all"],
                                     check=False, cwd=PROJECT, env=browser_env, capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", timeout=150,
                                     **HIDDEN)
            (EVIDENCE / "browser.stdout.txt").write_text(checked.stdout, encoding="utf-8")
            (EVIDENCE / "browser.stderr.txt").write_text(checked.stderr, encoding="utf-8")
            (EVIDENCE / "browser.exit.txt").write_text(str(checked.returncode), encoding="utf-8")
            print(checked.stdout, flush=True)
            if checked.returncode or "✗" in checked.stdout:
                raise RuntimeError("Browser four-scene regression failed")
            jobs = subprocess.run(["node", str(PROJECT / "scripts/verify-jobs.mjs")],
                                  check=False, cwd=PROJECT, env=browser_env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=150,
                                  **HIDDEN)
            (EVIDENCE / "jobs.stdout.txt").write_text(jobs.stdout, encoding="utf-8")
            (EVIDENCE / "jobs.stderr.txt").write_text(jobs.stderr, encoding="utf-8")
            (EVIDENCE / "jobs.exit.txt").write_text(str(jobs.returncode), encoding="utf-8")
            print(jobs.stdout, flush=True)
            if jobs.returncode:
                raise RuntimeError("Real jobs browser regression failed")
            learning = subprocess.run(["node", str(PROJECT / "scripts/verify-learning.mjs")],
                                      check=False, cwd=PROJECT, env=browser_env, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=150,
                                      **HIDDEN)
            (EVIDENCE / "learning.stdout.txt").write_text(learning.stdout, encoding="utf-8")
            (EVIDENCE / "learning.stderr.txt").write_text(learning.stderr, encoding="utf-8")
            (EVIDENCE / "learning.exit.txt").write_text(str(learning.returncode), encoding="utf-8")
            print(learning.stdout, flush=True)
            if learning.returncode:
                raise RuntimeError("Real learning/outbox browser regression failed")
            insights = subprocess.run(["node", str(PROJECT / "scripts/verify-job-insights.mjs")],
                                      check=False, cwd=PROJECT, env=browser_env, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=150,
                                      **HIDDEN)
            (EVIDENCE / "job-insights.stdout.txt").write_text(insights.stdout, encoding="utf-8")
            (EVIDENCE / "job-insights.stderr.txt").write_text(insights.stderr, encoding="utf-8")
            (EVIDENCE / "job-insights.exit.txt").write_text(str(insights.returncode), encoding="utf-8")
            print(insights.stdout, flush=True)
            if insights.returncode:
                raise RuntimeError("Real JD/weekly browser regression failed")
            studio = subprocess.run(["node", str(PROJECT / "scripts/verify-agent-studio.mjs")],
                                    check=False, cwd=PROJECT, env=browser_env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=150,
                                    **HIDDEN)
            (EVIDENCE / "agent-studio.stdout.txt").write_text(studio.stdout, encoding="utf-8")
            (EVIDENCE / "agent-studio.stderr.txt").write_text(studio.stderr, encoding="utf-8")
            (EVIDENCE / "agent-studio.exit.txt").write_text(str(studio.returncode), encoding="utf-8")
            print(studio.stdout, flush=True)
            if studio.returncode:
                raise RuntimeError("Real Agent memory/session studio browser regression failed")
            collab = subprocess.run(["node", str(PROJECT / "scripts/verify-collaboration.mjs")],
                                    check=False, cwd=PROJECT, env=browser_env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=150, **HIDDEN)
            (EVIDENCE / "collaboration.stdout.txt").write_text(collab.stdout, encoding="utf-8")
            (EVIDENCE / "collaboration.stderr.txt").write_text(collab.stderr, encoding="utf-8")
            (EVIDENCE / "collaboration.exit.txt").write_text(str(collab.returncode), encoding="utf-8")
            print(collab.stdout, flush=True)
            if collab.returncode:
                raise RuntimeError("Real collaboration browser regression failed")
            public = subprocess.run(["node", str(PROJECT / "scripts/verify-public-corpus.mjs")],
                                    check=False, cwd=PROJECT, env=browser_env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=150, **HIDDEN)
            (EVIDENCE / "public-corpus.stdout.txt").write_text(public.stdout, encoding="utf-8")
            (EVIDENCE / "public-corpus.stderr.txt").write_text(public.stderr, encoding="utf-8")
            (EVIDENCE / "public-corpus.exit.txt").write_text(str(public.returncode), encoding="utf-8")
            print(public.stdout, flush=True)
            if public.returncode:
                raise RuntimeError("Real public corpus browser regression failed")
            mcp = subprocess.run([sys.executable, str(PROJECT / "scripts/verify_mcp_queries.py")],
                                check=False, cwd=PROJECT, env=browser_env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=90, **HIDDEN)
            (EVIDENCE / "mcp-queries.stdout.txt").write_text(mcp.stdout, encoding="utf-8")
            (EVIDENCE / "mcp-queries.stderr.txt").write_text(mcp.stderr, encoding="utf-8")
            (EVIDENCE / "mcp-queries.exit.txt").write_text(str(mcp.returncode), encoding="utf-8")
            print(mcp.stdout, flush=True)
            if mcp.returncode:
                raise RuntimeError("Real SDK MCP business query verification failed")
            assert request(base, "/health/live")["status"] == "ok"
            assert request(base, "/health/ready")["status"] == "ok"
            diagnostics = request(base, "/api/admin/diagnostics")
            assert diagnostics["passed"] and diagnostics["checks"]
            print("PASS operations ready and redacted diagnostics", flush=True)
            browser("core")
            browser("prepare-failure")
            command([docker, "stop", "--time", "5", container])
            browser("database-offline")
            assert request(base, "/health/live")["status"] == "ok"
            try:
                # Allow the configured 3s DB deadline to return its actual 503.
                request(base, "/health/ready", timeout=10)
            except urllib.error.HTTPError as error:
                assert error.code == 503
            else:
                raise RuntimeError("Readiness incorrectly passed with PostgreSQL stopped")
            print("PASS liveness survives / readiness blocks database outage", flush=True)
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
            server_log.close()
            # Delete only a container whose random name AND ownership label match this run.
            try:
                owner = command([docker, "inspect", "--format",
                                 '{{index .Config.Labels "io.shilie.regression"}}', container]).strip()
                if owner == run_id:
                    try:
                        log = subprocess.run([docker, "logs", container], check=False, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=15, **HIDDEN)
                        (EVIDENCE / "postgres.stdout.txt").write_text(log.stdout + log.stderr, encoding="utf-8")
                        # State only, never Config.Env (which contains the QA password).
                        state = command([docker, "inspect", "--format", "{{json .State}}", container])
                        (EVIDENCE / "postgres-state.json").write_text(state, encoding="utf-8")
                    finally:
                        command([docker, "rm", "-f", "-v", container])
            except RuntimeError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--uds", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output:
        EVIDENCE = args.output.resolve()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    try:
        if args.serve:
            if args.uds is not None and args.port is not None:
                parser.error("Choose one QA listener")
            serve(args.serve, args.run_id, args.port, uds=args.uds)
        else:
            run()
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print("FAIL:", error, file=sys.stderr)
        sys.exit(1)
