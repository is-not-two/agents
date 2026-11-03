"""Run fail-closed local/CI release checks and write a machine-readable report."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from rag_tech_retriever.common.release_manifest import source_manifest
from rag_tech_retriever.platform.operations import configuration_report


def main() -> int:
    """No shell interpolation or deployment side effects; failure always blocks release."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT)
    parser.add_argument("--profile", choices=["local", "production"], default="local")
    parser.add_argument("--checks", choices=["config", "quick", "full"], default="quick")
    parser.add_argument("--backend", choices=["docker", "native"], default="native",
                        help="Full-check transport; native never falls back to Docker")
    parser.add_argument("--native-session", type=Path,
                        help="Operator-provided pinned SSH configuration for a fresh native QA session")
    parser.add_argument("--report", type=Path, default=PROJECT / "output/ci/gate.json")
    args = parser.parse_args()
    if args.backend == "native" and args.checks == "full" and args.native_session is None:
        parser.error("native full checks require an explicit --native-session; Docker is never implicit")
    if args.native_session is not None and args.checks != "full":
        parser.error("--native-session requires full checks")
    if args.native_session is not None and args.backend != "native":
        parser.error("--native-session requires --backend native")
    root = args.root.resolve()
    report = configuration_report(root, args.profile)
    report.update({"schema": 1, "level": args.checks,
                   "backend": args.backend if args.checks == "full" else None,
                   "created_at": datetime.now(timezone.utc).isoformat()})
    before = source_manifest(root)
    commands = []
    if args.checks != "config" and report["passed"]:
        commands = [[sys.executable, "-m", "pip", "check"],
                    # Generated evidence/rollback fixtures are not product source.
                    # Keep every published Python code directory in lint scope.
                    [sys.executable, "-m", "ruff", "check", "src", "scripts", "tests"],
                    [sys.executable, "scripts/check_static_version.py"],
                    # 契约漂移与静态版本一样属于「代码自洽」检查：不连数据库，
                    # 但有端点/模型变化未同步快照时阻断发布。
                    [sys.executable, "scripts/openapi_contract.py"]]
        commands += [["node", "--check", str(p)] for p in sorted(
            (root / "src/rag_tech_retriever/api/static/shilie").glob("*.js"))]
        commands += [["node", "--check", "scripts/verify-ui.mjs"]]
        commands += [[sys.executable, "scripts/agent_eval.py", "--report",
                      str(args.report.resolve().parent / "agent-contract.json")]]
        commands += [[sys.executable, "scripts/collaboration_eval.py", "--report",
                      str(args.report.resolve().parent / "collaboration-comparison.json")]]
        if args.checks == "full":
            if args.backend == "native":
                commands += [[sys.executable, "scripts/native_gate_client.py", "--session",
                              str(args.native_session.resolve()), "--output",
                              str(args.report.resolve().parent / "isolated")]]
            else:
                commands += [[sys.executable, "scripts/ci_verify.py", "--output",
                              str(args.report.resolve().parent / "isolated")]]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "RAG_PROJECT_ROOT": str(root), "PYTHONPATH": str(root / "src")}
    if args.checks == "full":
        # Diagnostic CI runs may use -k; a release must not inherit that selection.
        env["PYTEST_ADDOPTS"] = ""
    # The native owner has a 3000s OS lifecycle cap (pytest + session + cleanup).
    # Keep the outer supervisor longer so normal inner cleanup can finish.
    timeout = 3600 if args.checks == "full" else 120
    for command in commands:
        try:
            ran = subprocess.run(command, check=False, cwd=root, env=env, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=timeout)
            code, stdout, stderr = ran.returncode, ran.stdout, ran.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, stdout, stderr = 127, "", type(exc).__name__
        report["checks"].append({"id": "command_" + str(len(report["checks"])),
                                 "status": "pass" if code == 0 else "fail",
                                 "command": command, "exit": code,
                                 "stdout": stdout, "stderr": stderr})
        print(("PASS " if code == 0 else "FAIL ") + " ".join(command[:4]), flush=True)
        if code:
            report["passed"] = False
            break
    report["source_manifest"] = source_manifest(root)
    if before != report["source_manifest"]:
        report["passed"] = False
        report["checks"].append({"id": "source_stability", "status": "fail",
                                 "message": "验证期间发布源发生变化"})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("GATE_PASS" if report["passed"] else "GATE_BLOCKED")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
