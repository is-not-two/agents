"""No-production-DB tests: strict configuration, probes and source-bound packaging."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.config_loader import ConfigError, ConfigLoader
from rag_tech_retriever.common.release_manifest import source_manifest
from rag_tech_retriever.platform.operations import configuration_report
from rag_tech_retriever.platform.record_store import RecordStore, StorageError

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("text", ["web:\n  port: 1\n  port: 2\n", "x: 1\nx: 2\n", "[1, 2]"])
def test_yaml_rejects_ambiguous_or_non_mapping(tmp_path, text):
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigLoader(path, tmp_path / "no.env")


def config_root(tmp_path):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    return tmp_path


def test_local_report_and_secret_redaction(tmp_path):
    root = config_root(tmp_path)
    secret = "DO_NOT_LEAK_TOKEN_" * 3
    env = {"WORKSPACE_ACCESS_TOKEN": secret, "POSTGRES_PASSWORD": secret}
    report = configuration_report(root, "local", lambda k, d: env.get(k, d))
    assert report["passed"]
    assert secret not in json.dumps(report)


def test_production_profile_fails_closed(tmp_path):
    report = configuration_report(config_root(tmp_path), "production", lambda k, d: d)
    assert not report["passed"]
    assert {c["id"] for c in report["checks"] if c["status"] == "fail"} >= {"authentication", "database_secret"}


def test_production_profile_with_explicit_credentials(tmp_path):
    env = {"WORKSPACE_REQUIRE_AUTH": "true", "WORKSPACE_ACCESS_TOKEN": "x" * 40,
           "POSTGRES_PASSWORD": "not-an-example-password", "WEB_RATE_LIMIT_PER_MINUTE": "120"}
    report = configuration_report(config_root(tmp_path), "production", lambda k, d: env.get(k, d))
    assert report["passed"]
    assert env["POSTGRES_PASSWORD"] not in json.dumps(report)


def test_invalid_profile_is_not_returned_as_environment_value(tmp_path):
    secret = "INVALID_PROFILE_DO_NOT_ECHO"
    report = configuration_report(config_root(tmp_path), secret, lambda k, d: d)
    assert not report["passed"] and report["profile"] == "invalid"
    assert secret not in json.dumps(report)


def test_invalid_profile_rejects_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PROFILE", "prod-typo")
    with pytest.raises(RuntimeError, match="WORKSPACE_PROFILE"):
        create_app(store=ProbeStore(), root=tmp_path, token="")


@pytest.mark.parametrize("value", [True, -1, "8770", 99999])
def test_bad_port_is_not_silently_coerced(tmp_path, value):
    root = config_root(tmp_path)
    import yaml
    file = root / "config/web.yaml"
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    data["web"]["port"] = value
    file.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert not configuration_report(root, "local", lambda k, d: d)["passed"]


class ProbeStore:
    offline = True
    calls = 0
    def ensure_schema(self):
        pass
    def ping(self, timeout_seconds=3):
        self.calls += 1
        if self.offline:
            raise StorageError("SECRET_DSN_MUST_NOT_LEAK")
    @contextmanager
    def transaction(self):
        raise AssertionError("Liveness must not start a transaction")
        yield


def test_liveness_readiness_and_diagnostics(tmp_path):
    store = ProbeStore()
    with TestClient(create_app(store=store, root=tmp_path, token="")) as client:
        live = client.get("/health/live")
        assert live.status_code == 200 and store.calls == 0
        down = client.get("/health/ready")
        assert down.status_code == 503 and "SECRET_DSN" not in down.text
        store.offline = False
        assert client.get("/health/ready").status_code == 200
        result = client.get("/api/admin/diagnostics")
        assert result.status_code == 200 and result.json()["checks"]
        assert result.json()["request_id"]


def test_diagnostics_uses_global_auth(tmp_path):
    with TestClient(create_app(store=ProbeStore(), root=tmp_path, token="test-token")) as client:
        assert client.get("/api/admin/diagnostics").status_code == 401
        assert client.get("/health/live").status_code == 200


def test_production_startup_rejects_missing_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PROFILE", "production")
    monkeypatch.setenv("WORKSPACE_ACCESS_TOKEN", "")
    monkeypatch.setenv("WORKSPACE_REQUIRE_AUTH", "false")
    with pytest.raises(RuntimeError, match="生产配置预检失败"):
        create_app(store=ProbeStore(), root=tmp_path, token="")


@pytest.mark.parametrize("timeout", [True, 0, 11, 2.5, None])
def test_probe_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        RecordStore("qa_probe").ping(timeout_seconds=timeout)


def test_probe_timeout_and_close(monkeypatch):
    seen = {}
    class Cursor:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql):
            seen["sql"] = sql
        def fetchone(self):
            return (1,)
    class Connection:
        def cursor(self):
            return Cursor()
        def close(self):
            seen["closed"] = True
    def connect(**kwargs):
        seen.update(kwargs)
        return Connection()
    monkeypatch.setattr("rag_tech_retriever.platform.record_store.psycopg2.connect", connect)
    RecordStore("qa_probe").ping(timeout_seconds=3)
    assert seen["connect_timeout"] == 3
    assert seen["options"] == "-c statement_timeout=3000"
    assert seen["sql"] == "SELECT 1" and seen["closed"]


def package_module():
    spec = importlib.util.spec_from_file_location("release_package_test", ROOT / "scripts/release_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_fixture(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('ok')\n")
    (tmp_path / ".env").write_text("TOKEN=PRIVATE")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/private.json").write_text("PRIVATE")
    report = tmp_path / "gate.json"
    report.write_text(json.dumps({"schema": 1, "level": "full", "passed": True,
                                  "source_manifest": source_manifest(tmp_path)}))
    return report


def test_package_source_binding_and_private_exclusion(tmp_path):
    report = release_fixture(tmp_path)
    out = tmp_path / "release.zip"
    result = package_module().build(tmp_path, report, out)
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {"src/app.py", "RELEASE-MANIFEST.json"}
        assert z.testzip() is None
    assert out.with_suffix(".zip.sha256").read_text().startswith(result["sha256"])
    with pytest.raises(ValueError, match="拒绝覆盖"):
        package_module().build(tmp_path, report, out)


@pytest.mark.parametrize("mutation", ["failed", "quick", "stale", "empty"])
def test_package_rejects_bad_proof(tmp_path, mutation):
    report = release_fixture(tmp_path)
    data = json.loads(report.read_text())
    if mutation == "failed":
        data["passed"] = False
    elif mutation == "quick":
        data["level"] = "quick"
    elif mutation == "empty":
        data.clear()
    else:
        (tmp_path / "src/app.py").write_text("print('changed')\n")
    report.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        package_module().build(tmp_path, report, tmp_path / "release.zip")
    assert not (tmp_path / "release.zip").exists()


def test_config_gate_exit_and_report(tmp_path):
    root = config_root(tmp_path)
    file = root / "config/web.yaml"
    file.write_text("web:\n  port: 1\n  port: 2\n", encoding="utf-8")
    report = tmp_path / "gate.json"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/release_gate.py"),
                             "--root", str(root), "--checks", "config", "--report", str(report)],
                            check=False, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 1
    assert not json.loads(report.read_text(encoding="utf-8"))["passed"]


def test_workflows_pin_official_actions_and_never_deploy():
    from rag_tech_retriever.common.config_loader import load_yaml_mapping
    for name in ["ci", "release"]:
        path = ROOT / ".github/workflows" / (name + ".yml")
        workflow = load_yaml_mapping(path)
        assert workflow["permissions"] == {"contents": "read"}
        assert "pull_request_target" not in workflow["on"]
        text = path.read_text()
        assert "ssh " not in text and "secrets." not in text
        import re
        assert all(re.fullmatch(r"actions/[a-z-]+@[a-f0-9]{40}", step["uses"])
                   for step in workflow["jobs"]["verify"]["steps"] if "uses" in step)
    assert workflow["on"] == {"workflow_dispatch": None}
    assert workflow["jobs"]["verify"]["environment"] == "release"
