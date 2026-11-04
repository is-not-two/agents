"""部署脚本的隔离运行时防护：拒绝旧流程覆盖已隔离的 preview。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deploy_release", ROOT / "scripts/deploy_release.py")
DEPLOY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(DEPLOY)


@pytest.mark.parametrize(
    ("user", "exec_start", "isolated"),
    [
        ("shilie_pvapp", "{ path=/var/lib/shilie-preview/app/.venv/bin/python }", True),
        ("shilie", "{ path=/var/lib/shilie-preview/app/.venv/bin/python }", True),
        ("shilie_pvapp", "{ path=/opt/shilie/preview/.venv/bin/python }", True),
        ("shilie", "{ path=/opt/shilie/preview/.venv/bin/python }", False),
        ("", "", False),
    ],
)
def test_preview_runtime_isolation_detection(user, exec_start, isolated):
    """身份或执行路径任一指向隔离根，就必须判定为已隔离并中止旧部署。"""
    assert DEPLOY.preview_runtime_isolated(user, exec_start) is isolated


def test_deploy_script_refuses_before_any_remote_write():
    """防护必须在预检阶段抛出 DeployError，而不是部署到一半才发现。"""
    source = (ROOT / "scripts/deploy_release.py").read_text(encoding="utf-8")
    guard = source.index('if SERVICE == "shilie-preview" and preview_runtime_isolated(')
    first_write = source.index("def deploy(")
    assert guard < first_write
    window = source[guard:guard + 700]
    assert "raise DeployError" in window
    assert "破坏隔离" in window
