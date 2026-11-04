"""8771 隔离部署脚本的边界：只认隔离运行时与整目录布局。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deploy_preview_isolated", ROOT / "scripts/deploy_preview_isolated.py"
)
DEPLOY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(DEPLOY)


@pytest.mark.parametrize(
    ("user", "exec_start", "expected"),
    [
        ("shilie_pvapp", "{ path=/var/lib/shilie-preview/app/.venv/bin/python }", True),
        ("shilie", "{ path=/var/lib/shilie-preview/app/.venv/bin/python }", False),
        ("shilie_pvapp", "{ path=/opt/shilie/preview/.venv/bin/python }", False),
        ("", "", False),
    ],
)
def test_isolated_runtime_requires_both_identity_and_root(user, exec_start, expected):
    """身份与执行路径必须同时落在隔离根，缺一即中止，避免误部署到共享运行时。"""
    assert DEPLOY.isolated_runtime(user, exec_start) is expected


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("directory", True), ("symbolic link", False), ("missing", False), ("", False)],
)
def test_layout_requires_plain_directory(kind, expected):
    """整目录换位只支持普通目录；软链布局必须显式拒绝而不是猜。"""
    assert DEPLOY.layout_is_plain_dir(kind) is expected


def test_constants_never_point_at_shared_runtime():
    """脚本常量不得落到正式根或共享 /var/lib/shilie。"""
    assert DEPLOY.PREVIEW_APP == "/var/lib/shilie-preview/app"
    assert DEPLOY.PREVIEW_ROOT == "/var/lib/shilie-preview"
    assert DEPLOY.PREVIEW_USER == "shilie_pvapp"
    assert DEPLOY.PREVIEW_DB == "shilie_preview_20261104"
    assert DEPLOY.PREVIEW_PG_PORT == 55433
    assert not DEPLOY.PREVIEW_ROOT.startswith("/var/lib/shilie/")
    assert "/opt/shilie" not in DEPLOY.PREVIEW_APP


def test_guard_runs_in_preflight_before_any_remote_write():
    """身份/布局校验必须在 deploy() 之前抛出，不能在换位后才发现。"""
    source = (ROOT / "scripts/deploy_preview_isolated.py").read_text(encoding="utf-8")
    guard = source.index("if not isolated_runtime(")
    first_write = source.index("def deploy(")
    assert guard < first_write
    window = source[guard:guard + 900]
    assert "raise base.DeployError" in window


def test_swap_moves_old_app_before_start():
    """换位与启动分离：启动失败时脚本已拿到旧目录，才能自动换回。"""
    source = (ROOT / "scripts/deploy_preview_isolated.py").read_text(encoding="utf-8")
    swap_body = source[source.index("def swap("):source.index("def start_service(")]
    assert 'mv "$APP" "$OLD"' in swap_body
    assert "systemctl start" not in swap_body
    assert "def start_service(" in source
