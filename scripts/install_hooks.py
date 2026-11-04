"""安装 git pre-push hook：推送前自动跑本地门禁。

设计要点
- 只拦截 push，不拦截 commit——提交要快，推送才值得检查。
- hook 内容自包含（不依赖外部文件），落后可随时用本脚本重装。
- 支持 GATE_SKIP=1 临时跳过（会打印明显警告），保证紧急情况下不被锁死。
- Windows 下 git 用 sh 执行 hook，因此 hook 是 POSIX sh 脚本。

用法：
    python scripts/install_hooks.py           # 安装
    python scripts/install_hooks.py --remove  # 卸载
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]

HOOK = """#!/bin/sh
# 由 scripts/install_hooks.py 生成；重装会覆盖，请勿直接编辑。
# 推送前跑本地门禁；GATE_SKIP=1 可临时跳过（会打印警告）。

if [ "$GATE_SKIP" = "1" ]; then
  echo ""
  echo "!! 已跳过门禁（GATE_SKIP=1）——请确认这是有意为之"
  echo ""
  exit 0
fi

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT" || exit 1

PY=""
if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  echo "未找到 .venv，跳过门禁（建议先建虚拟环境）"
  exit 0
fi

if [ ! -f "scripts/ci_gate.py" ]; then
  echo "未找到 scripts/ci_gate.py，跳过门禁"
  exit 0
fi

echo ""
echo "运行 CI 门禁（约 15 秒，不依赖数据库）..."
echo ""
"$PY" scripts/ci_gate.py || {
  echo ""
  echo "门禁未通过，推送已中止。"
  echo "确认无碍后可用：GATE_SKIP=1 git push"
  exit 1
}

exit 0
"""


def hooks_dir() -> Path:
    """返回本项目 hooks 目录（支持 worktree）。"""
    done = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=PROJECT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if done.returncode != 0:
        raise SystemExit(f"不是 git 仓库：{done.stderr.strip()}")
    path = Path(done.stdout.strip())
    return path if path.is_absolute() else (PROJECT / path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true", help="卸载 hook")
    args = parser.parse_args()

    target = hooks_dir() / "pre-push"

    if args.remove:
        if target.exists():
            target.unlink()
            print(f"已移除 {target}")
        else:
            print("hook 不存在，无需移除")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(HOOK.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    print(f"已安装 {target}")
    print()
    print("行为：git push 前自动跑 scripts/ci_gate.py（约 15 秒，不依赖 PostgreSQL/Docker）")
    print("  - 失败则中止推送")
    print("  - 紧急跳过：GATE_SKIP=1 git push")
    print(f"  - 卸载：python {Path(__file__).name} --remove")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
