"""Backend selection is explicit; native checks never fall back to Docker."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def gate():
    """Load the real command builder without running its external commands."""
    spec = importlib.util.spec_from_file_location("native_gate_policy", ROOT / "scripts/release_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("arguments", [
    ["--checks", "full"],
    ["--backend", "native", "--checks", "full"],
    ["--backend", "docker", "--native-session", "operator.json", "--checks", "full"],
    ["--backend", "native", "--checks", "quick", "--native-session", "operator.json"],
])
def test_native_backend_rejects_incomplete_or_ambiguous_selection(gate, monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", ["release_gate.py", *arguments])
    with pytest.raises(SystemExit) as error:
        gate.main()
    assert error.value.code == 2


@pytest.mark.parametrize("native_exit", [0, 19])
def test_full_native_builds_real_client_command_and_propagates_failure(
    gate, monkeypatch, tmp_path, native_exit
):
    """Unit contract only: real HTTP/browser coverage belongs to the full gate."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("pass\n", encoding="utf-8")
    report = tmp_path / "evidence/gate.json"
    session = tmp_path / "operator.json"
    monkeypatch.setattr(sys, "argv", ["release_gate.py", "--root", str(tmp_path),
        "--checks", "full", "--backend", "native", "--native-session", str(session),
        "--report", str(report)])
    monkeypatch.setattr(gate, "configuration_report", lambda *_: {"passed": True, "checks": []})
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        code = native_exit if "scripts/native_gate_client.py" in command else 0
        return subprocess.CompletedProcess(command, code, "unit-contract-output", "")

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main() == (0 if native_exit == 0 else 1)
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["passed"] is (native_exit == 0)
    assert data["backend"] == "native" and data["level"] == "full"
    commands = [command for command, _ in calls]
    assert commands[-1] == [sys.executable, "scripts/native_gate_client.py", "--session",
        str(session.resolve()), "--output", str(report.parent.resolve() / "isolated")]
    assert not any("scripts/ci_verify.py" in command or "docker" in command for command in commands)
    assert [sys.executable, "-m", "ruff", "check", "src", "scripts", "tests"] in commands
    assert all(kwargs["env"]["PYTEST_ADDOPTS"] == "" for _, kwargs in calls)
    assert data["source_manifest"] == gate.source_manifest(tmp_path)


def test_openapi_contract_drift_blocks_gate(gate, monkeypatch, tmp_path):
    """契约快照必须进入门禁命令；漂移（非零退出）即阻断发布。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("pass\n", encoding="utf-8")
    report = tmp_path / "gate.json"
    monkeypatch.setattr(sys, "argv", ["release_gate.py", "--root", str(tmp_path),
        "--checks", "quick", "--report", str(report)])
    monkeypatch.setattr(gate, "configuration_report", lambda *_: {"passed": True, "checks": []})
    calls = []

    def run(command, **_):
        calls.append(command)
        code = 1 if command[-1].endswith("openapi_contract.py") else 0
        return subprocess.CompletedProcess(command, code, "", "")

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main() == 1
    assert [sys.executable, "scripts/openapi_contract.py"] in calls
    assert not json.loads(report.read_text(encoding="utf-8"))["passed"]


def test_native_client_success_cannot_hide_source_change(gate, monkeypatch, tmp_path):
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/app.py"
    source.write_text("pass\n", encoding="utf-8")
    report = tmp_path / "gate.json"
    monkeypatch.setattr(sys, "argv", ["release_gate.py", "--root", str(tmp_path),
        "--checks", "full", "--backend", "native", "--native-session", str(tmp_path / "operator.json"),
        "--report", str(report)])
    monkeypatch.setattr(gate, "configuration_report", lambda *_: {"passed": True, "checks": []})

    def run(command, **_):
        if "scripts/native_gate_client.py" in command:
            source.write_text("raise RuntimeError('changed')\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main() == 1
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["checks"][-1]["id"] == "source_stability"
    assert not data["passed"]
