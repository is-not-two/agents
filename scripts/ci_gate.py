"""跨平台只读 CI 门禁：ruff、契约、静态资源与纯逻辑 pytest（不依赖 PostgreSQL）。

用于 Gitee Go 主机组、服务器自托管 runner 或本地手动执行；
任何一步失败立即以非零退出码结束，不写入数据库、不启动服务。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKS: list[tuple[str, list[str]]] = [
    # 测试只存在于本地（不入库），发布包/远端没有 tests/ 时不能把它当 ruff 目标。
    ("ruff 代码检查", [sys.executable, "-m", "ruff", "check", "src", "scripts"]
     + (["tests"] if (ROOT / "tests").is_dir() else [])),
    ("OpenAPI 契约一致", [sys.executable, "scripts/openapi_contract.py"]),
    ("前端接口契约一致", [sys.executable, "scripts/frontend_api_contract.py"]),
    ("Vue wheel 与静态资源", [sys.executable, "scripts/check_vue_candidate.py"]),
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
    "tests/test_vue_source_layout.py",
    "tests/test_release_fixture_hashes.py",
    "tests/test_private_backup_preflight.py",
    "tests/test_self_traits.py",
    "tests/test_workflow_composer.py",
    "tests/test_code_workspace.py",
    "tests/test_resume_optimizer.py",
    "tests/test_kind_migration.py",
    "tests/test_interview_prep.py",
    "tests/test_interview_prep_answers.py",
    "tests/test_interview_evaluation.py",
    "tests/test_simulation_cards.py",
    "tests/test_agent_job_tools.py",
    # 未安装 agent-framework 时整文件跳过；装了的环境（Python 3.11+）跑真实编排。
    "tests/test_maf_runtime.py",
    "tests/test_team_service.py",
    "tests/test_coding_loop.py",
    "tests/test_model_attempt.py",
    "tests/test_aider_attempt.py",
    "tests/test_opencode_attempt.py",
    "tests/test_loop_service.py",
    "tests/test_task_queue.py",
    "tests/test_queue_worker.py",
]


def run(name: str, command: list[str], timeout: int = 300) -> tuple[bool, str]:
    started = time.time()
    # Windows 下系统默认编码是 GBK，而 pytest/ruff/Vite 的子进程输出常含 UTF-8
    # 中文；text=True 会按 GBK 解码抛 UnicodeDecodeError（曾让整个门禁崩溃）。
    # 强制子进程与解码都用 UTF-8，解码异常用 replace 兜底，门禁结果不因编码失真。
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    # 从 git hook / push 上下文调用时会继承 GIT_DIR 等变量；测试里新建临时仓库再
    # git commit 就会作用到本仓库（2026-11-24 实测污染过 develop）。这里统一剔除。
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                "GIT_PREFIX", "GIT_QUARANTINE_PATH"):
        env.pop(key, None)
    try:
        result = subprocess.run(command, check=False, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{name} 超时（{timeout}s）"
    except OSError:
        return False, f"{name} 执行器不可用，请检查已安装的运行时"
    elapsed = time.time() - started
    if result.returncode == 0:
        return True, f"[OK] {name} ({elapsed:.1f}s)"
    tail = (result.stdout + result.stderr).strip().splitlines()[-6:]
    joined = "\n".join(tail)
    return False, f"[FAIL] {name} ({elapsed:.1f}s)\n{joined}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop-ui", action="store_true", help="执行隔离桌面浏览器交互门禁（需 Node/Playwright）")
    parser.add_argument("--vue-candidate", action="store_true", help="兼容旧命令；Vue 包验收已是默认步骤")
    args = parser.parse_args()
    failures: list[str] = []
    print("=" * 56)
    print("CI 只读门禁（不依赖 PostgreSQL / Docker）")
    print("=" * 56)
    checks = CHECKS + ([("桌面 Vue 交互", [sys.executable, "scripts/check_vue_browser.py"])] if args.desktop_ui else [])
    for name, command in checks:
        ok, message = run(name, command)
        print(message)
        if not ok:
            failures.append(name)
    if not failures and (ROOT / "tests").is_dir():
        ok, message = run("纯逻辑 pytest", [sys.executable, "-m", "pytest", "-q"] + PURE_LOGIC_TESTS, timeout=600)
        print(message)
        if not ok:
            failures.append("纯逻辑 pytest")
    elif not (ROOT / "tests").is_dir():
        # 测试文件不随仓库分发（2026-11-24 规定），远端与发布包内没有 tests/。
        print("[SKIP] 纯逻辑 pytest：tests/ 未入库，本目录没有测试文件")
    print("=" * 56)
    if failures:
        print(f"CI_GATE_FAILED：{'、'.join(failures)}")
        return 1
    print("CI_GATE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
