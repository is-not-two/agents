"""部署脚本的旧 release 清理规则（纯字符串断言，不连服务器）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    """按路径加载部署脚本，避免依赖脚本目录在 sys.path 上。"""
    spec = importlib.util.spec_from_file_location(
        "deploy_release_under_test", ROOT / "scripts" / "deploy_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prune_script_never_deletes_live_symlink_targets():
    """正式与测试两个软链指向的版本必须排除在清理之外。"""
    script = _module().prune_script(2)
    assert "readlink -f" in script
    assert '"$CUR"' in script and '"$PRE"' in script
    assert 'if [ "$name" = "$CUR" ] || [ "$name" = "$PRE" ]; then continue; fi' in script


def test_prune_script_honours_keep_count():
    script = _module().prune_script(3)
    assert "if [ $COUNT -gt 3 ]" in script
    assert 'rm -rf -- "$name"' in script


def test_prune_script_only_touches_native_releases():
    script = _module().prune_script(2)
    assert "ls -1dt native-*" in script
    assert "cd /opt/shilie/releases" in script
