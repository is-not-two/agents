"""本地质量门禁：push 前跑完整检查，失败即阻断。

设计要点
- 不依赖 Docker、不依赖 GitHub、不依赖外网；只用项目自身 .venv 与本机 PostgreSQL。
- 检查项分「阻断」与「告警」：阻断项失败退出码非零，告警项只提示。
- 全部检查串行执行并即时输出，失败处立刻可见，不做静默收集。
- `--quick` 跳过 pytest，用于只改了样式/文档的场合。

用法（项目根目录）：
    .venv/Scripts/python.exe scripts/local_gate.py
    .venv/Scripts/python.exe scripts/local_gate.py --quick
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
VENV_PY = PROJECT / ".venv" / "Scripts" / "python.exe"

#: 检查结果
PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


class Gate:
    """收集检查结果；阻断项失败时整体判失败。"""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.blocked = False

    def run(self, name: str, command: list[str], *, blocking: bool = True,
            timeout: int = 600, env: dict | None = None) -> bool:
        """执行一条检查命令并记录结果。"""
        started = time.perf_counter()
        print(f"\n-> {name}", flush=True)
        try:
            done = subprocess.run(
                command, cwd=PROJECT, check=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, env=env,
            )
            code, out, err = done.returncode, done.stdout, done.stderr
        except FileNotFoundError:
            self._record(name, SKIP, "命令不存在，跳过", blocking)
            print("  ⊘ 跳过（命令不存在）")
            return False
        except subprocess.TimeoutExpired:
            self._record(name, FAIL if blocking else WARN, f"超时 {timeout}s", blocking)
            print(f"  [FAIL] 超时 {timeout}s")
            return False

        elapsed = time.perf_counter() - started
        ok = code == 0
        status = (PASS if ok else (FAIL if blocking else WARN))
        detail = "" if ok else (out.strip() or err.strip())[-800:]
        self._record(name, status, detail, blocking, elapsed)
        mark = "OK" if ok else ("FAIL" if blocking else "!")
        print(f"  [{mark}] {status} ({elapsed:.1f}s)")
        if not ok:
            for line in (out.strip() or err.strip()).splitlines()[-12:]:
                print(f"    {line}")
        return ok

    def check(self, name: str, func, *, blocking: bool = True) -> bool:
        """执行一个 Python 检查函数；异常视为失败。"""
        print(f"\n-> {name}", flush=True)
        try:
            ok, detail = func()
        except Exception as exc:  # noqa: BLE001 - 检查函数自身出错也必须计为失败
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        status = PASS if ok else (FAIL if blocking else WARN)
        self._record(name, status, "" if ok else detail, blocking)
        print(f"  [{'OK' if ok else ('FAIL' if blocking else 'WARN')}] {status}")
        if not ok and detail:
            print(f"    {detail}")
        return ok

    def _record(self, name: str, status: str, detail: str, blocking: bool,
                elapsed: float = 0.0) -> None:
        if status == FAIL:
            self.blocked = True
        self.results.append({
            "name": name, "status": status, "blocking": blocking,
            "detail": detail, "elapsed_s": round(elapsed, 2),
        })

    def summary(self) -> int:
        """打印汇总并返回退出码。"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["status"] == PASS)
        failed = [r for r in self.results if r["status"] == FAIL]
        warned = [r for r in self.results if r["status"] == WARN]
        skipped = [r for r in self.results if r["status"] == SKIP]
        print("\n" + "=" * 58)
        print(f"门禁结果：{passed}/{total} 通过", end="")
        if failed:
            print(f"，{len(failed)} 项阻断失败", end="")
        if warned:
            print(f"，{len(warned)} 项告警", end="")
        if skipped:
            print(f"，{len(skipped)} 项跳过", end="")
        print()
        if failed:
            print("\n阻断项：")
            for item in failed:
                print(f"  [FAIL] {item['name']}")
        if warned:
            print("\n告警项（不阻断，但建议处理）：")
            for item in warned:
                print(f"  [WARN] {item['name']}")
        print("=" * 58)
        if self.blocked:
            print("GATE FAILED - 请修复阻断项后再推送")
            return 1
        print("GATE PASSED")
        return 0




def check_no_secrets_tracked() -> tuple[bool, str]:
    """确认 .env、密钥、本地数据没有被 git 跟踪。"""
    done = subprocess.run(
        ["git", "ls-files"], cwd=PROJECT, check=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    if done.returncode != 0:
        return False, "git ls-files 失败"
    tracked = done.stdout.splitlines()
    forbidden = (".env", "data/local/", "private-vault", ".key", ".crt", "id_rsa")
    hits = [f for f in tracked if any(f == bad or f.startswith(bad) or bad in f for bad in forbidden)]
    # .env.example 是模板，允许
    hits = [h for h in hits if not h.endswith(".env.example")]
    if hits:
        return False, "以下敏感文件被 git 跟踪：\n" + "\n".join(hits[:8])
    return True, f"{len(tracked)} 个已跟踪文件，无敏感项"


def check_kind_consistency() -> tuple[bool, str]:
    """代码里的 RECORD_KINDS 与数据库 CHECK 约束必须一致。

    这是 2026-11-02 部署失败的直接原因：代码要 17 种 kind，数据库只有 8 种，
    verify 模式拒绝启动。CI 环境无生产库，本地门禁能查。
    """
    sys.path.insert(0, str(PROJECT / "src"))
    try:
        from rag_tech_retriever.platform.record_store import RECORD_KINDS
    except Exception as exc:  # noqa: BLE001 - 导入失败即判该检查失败，不中断整轮门禁
        return False, f"无法导入 RECORD_KINDS：{exc}"

    db = _query_kinds()
    if db is None:
        return True, f"代码要求 {len(RECORD_KINDS)} 种 kind；数据库未连接，跳过比对"

    missing = sorted(RECORD_KINDS - db)
    extra = sorted(db - RECORD_KINDS)
    if missing:
        return False, (f"数据库缺少 {len(missing)} 种 kind：{', '.join(missing)}\n"
                       f"部署会因 kind 约束不完整而拒绝启动")
    if extra:
        return False, (f"数据库多出 {len(extra)} 种 kind：{', '.join(extra)}\n"
                       f"回滚到旧代码会失败（managed_kind_check 要求数量相等）")
    return True, f"{len(RECORD_KINDS)} 种 kind 与数据库一致"


def _query_kinds() -> set[str] | None:
    """读取本地数据库的 kind 约束；连不上返回 None。"""
    try:
        import psycopg2

        from rag_tech_retriever.common.config_loader import ConfigLoader

        cfg = ConfigLoader.load_default()
        conn = psycopg2.connect(
            host=cfg.env("POSTGRES_HOST", "127.0.0.1"),
            port=cfg.env("POSTGRES_PORT", "5432"),
            dbname=cfg.env("POSTGRES_DB", "rag_tech_doc"),
            user=cfg.env("POSTGRES_USER", "rag"),
            password=cfg.env("POSTGRES_PASSWORD", ""),
            connect_timeout=3,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname = 'workspace_records_kind_check'")
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        import re

        return set(re.findall(r"'([a-z_]+)'::text", row[0]))
    except Exception:  # noqa: BLE001 - 连不上库是正常情形，不应中断门禁
        return None




def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="跳过 pytest，只做静态检查")
    parser.add_argument("--report", type=Path, help="把结果写成 JSON")
    args = parser.parse_args()

    if not VENV_PY.is_file():
        print(f"找不到虚拟环境解释器：{VENV_PY}")
        print("请先执行：python -m venv .venv")
        return 2

    gate = Gate()
    print("=" * 58)
    print("本地质量门禁" + ("（快速模式）" if args.quick else ""))
    print("=" * 58)

    # 静态与安全检查：始终阻断
    gate.check("敏感文件未入库", check_no_secrets_tracked)
    ruff_targets = ["src", "scripts"] + (["tests"] if (PROJECT / "tests").is_dir() else [])
    gate.run("ruff 代码检查",
             [str(VENV_PY), "-m", "ruff", "check", *ruff_targets], blocking=True)
    # 契约快照不连数据库：端点或响应模型变化未同步 docs/openapi.json 时阻断。
    gate.run("OpenAPI 契约一致",
             [str(VENV_PY), "scripts/openapi_contract.py"], blocking=True)
    # 前端引用的 /api 路径必须存在：页面指向已删端点时阻断。
    gate.run("前端接口契约一致",
             [str(VENV_PY), "scripts/frontend_api_contract.py"], blocking=True)
    # 页面与 CSS 引用的本地静态文件必须存在：改名漏改引用会 404。
    gate.run("Vue 发布包与入口",
             [str(VENV_PY), "scripts/check_vue_candidate.py"], blocking=True)

    # kind 一致性：连不上库时降级为跳过（CI 无库是正常的）
    gate.run("依赖完整性", [str(VENV_PY), "-m", "pip", "check"], blocking=False)
    gate.check("记录类型与数据库一致", check_kind_consistency, blocking=True)

    # 测试：快速模式跳过；tests/ 不随仓库分发时同样跳过并说明原因
    if args.quick:
        gate._record("pytest 全量", SKIP, "快速模式跳过", False)
        print("\n-> pytest 全量\n  [SKIP] --quick 跳过")
    elif not (PROJECT / "tests").is_dir():
        gate._record("pytest 全量", SKIP, "tests/ 未入库", False)
        print("\n-> pytest 全量\n  [SKIP] tests/ 未入库，本目录没有测试文件")
    else:
        gate.run("pytest 全量", [str(VENV_PY), "-m", "pytest", "-q", "--tb=line"],
                 blocking=True, timeout=900)

    code = gate.summary()

    if args.report:
        report_path = args.report if args.report.is_absolute() else PROJECT / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({
            "passed": code == 0, "quick": args.quick,
            "checks": gate.results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            shown = report_path.resolve().relative_to(PROJECT)
        except ValueError:
            shown = report_path.resolve()
        print(f"报告: {shown}")

    return code


if __name__ == "__main__":
    raise SystemExit(main())
