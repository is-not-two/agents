"""跨平台只读 CI 门禁：ruff、契约、静态资源与纯逻辑 pytest（不依赖 PostgreSQL）。

用于 Gitee Go 主机组、服务器自托管 runner 或本地手动执行；
任何一步失败立即以非零退出码结束，不写入数据库、不启动服务。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKS: list[tuple[str, list[str]]] = [
    ("ruff 代码检查", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]),
    ("静态版本号一致", [sys.executable, "scripts/check_static_version.py"]),
    ("OpenAPI 契约一致", [sys.executable, "scripts/openapi_contract.py"]),
    ("前端接口契约一致", [sys.executable, "scripts/frontend_api_contract.py"]),
    ("静态资源引用完整", [sys.executable, "scripts/check_static_assets.py"]),
    ("wheel 实际静态资产完整", [sys.executable, "scripts/check_wheel_assets.py", "--build"]),
]

PURE_LOGIC_TESTS = [
    "tests/test_record_store_pool.py",
    "tests/test_frontend_contract.py",
    "tests/test_package_hygiene.py",
    "tests/test_deploy_prune.py",
    "tests/test_export_cleanup.py",
    "tests/test_auth_module.py",
    "tests/test_openapi_contract.py",
    "tests/test_native_gate_policy.py",
    "tests/test_config_merge.py",
    "tests/test_deploy_guard.py",
    "tests/test_deploy_preview_isolated.py",
    "tests/test_trash_overview.py",
    "tests/test_prompt_optimizer.py",
    "tests/test_wheel_assets.py",
    "tests/test_release_fixture_hashes.py",
]


def run(name: str, command: list[str], timeout: int = 300) -> tuple[bool, str]:
    started = time.time()
    try:
        result = subprocess.run(command, check=False, cwd=ROOT, capture_output=True, text=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{name} 超时（{timeout}s）"
    elapsed = time.time() - started
    if result.returncode == 0:
        return True, f"[OK] {name} ({elapsed:.1f}s)"
    tail = (result.stdout + result.stderr).strip().splitlines()[-6:]
    joined = "\n".join(tail)
    return False, f"[FAIL] {name} ({elapsed:.1f}s)\n{joined}"


def main() -> int:
    failures: list[str] = []
    print("=" * 56)
    print("CI 只读门禁（不依赖 PostgreSQL / Docker）")
    print("=" * 56)
    for name, command in CHECKS:
        ok, message = run(name, command)
        print(message)
        if not ok:
            failures.append(name)
    if not failures:
        ok, message = run("纯逻辑 pytest", [sys.executable, "-m", "pytest", "-q"] + PURE_LOGIC_TESTS, timeout=600)
        print(message)
        if not ok:
            failures.append("纯逻辑 pytest")
    print("=" * 56)
    if failures:
        print(f"CI_GATE_FAILED：{'、'.join(failures)}")
        return 1
    print("CI_GATE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
