"""前端接口契约检查器的纯逻辑回归（不读真实前端文件、不连服务）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    """按路径加载脚本，避免依赖脚本目录在 sys.path 上。"""
    spec = importlib.util.spec_from_file_location(
        "frontend_contract_under_test", ROOT / "scripts" / "frontend_api_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_calls_handles_multiline_and_templates():
    """跨行调用、模板参数与 fetch 都被识别；helper 自身的 "/api/" 被排除。"""
    text = """
      await api("knowledge");
      const saved = await api(
        `plans/${id}`,
        { version },
      );
      await fetch("/api/status");
      await fetch("/api/" + path);
    """
    calls = _module().extract_calls(text)
    assert calls == {"/api/knowledge", "/api/plans/${id}", "/api/status"}


def test_matches_accepts_param_and_prefix_segments():
    module = _module()
    assert module.matches("/api/private/wish", "/api/private/{kind}")
    assert module.matches("/api/private/wish/", "/api/private/{kind}/{record_id}", prefix=True)
    # 前缀模式下等长且参数段可匹配也算命中
    assert module.matches("/api/private/wish/", "/api/private/{kind}", prefix=True)
    # 端点段数少于调用前缀时不算命中
    assert not module.matches("/api/private/wish/", "/api/private", prefix=True)
    # 非前缀模式必须段数一致
    assert not module.matches("/api/private/wish", "/api/private/{kind}/{record_id}")


def test_extract_calls_ignores_non_api_strings():
    text = 'api("session") ; fetch("http://x/api/y")'
    assert _module().extract_calls(text) == {"/api/session"}
