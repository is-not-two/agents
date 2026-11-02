"""设置账号登录密码：交互输入，生成哈希，密码不落盘不进日志。

密码明文只在你的终端内输入一次，脚本输出的是 scrypt 哈希；
把两行配置写进环境变量即可启用账号登录，代码与仓库里永远只有哈希。

用法（在项目根目录，用项目虚拟环境）：
    python scripts/set_login_password.py            # 生成哈希（交互输入密码）
    python scripts/set_login_password.py --check    # 用哈希验证一个密码是否正确
    python scripts/set_login_password.py --user luojiee   # 指定账号名（默认 luojiee）

启用步骤（生成后按提示操作）：
    本地开发：把输出的两行追加到项目根 .env
    服务器：  追加到 /etc/shilie/workspace.env 后 systemctl restart shilie
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from rag_tech_retriever.common.account_auth import (
    PasswordHashError,
    make_password_hash,
    verify_password,
)


def _read_password(prompt: str, confirm: bool) -> str:
    """读取密码：两次输入一致才通过，全程不回显。"""
    first = getpass.getpass(prompt)
    if not first:
        raise SystemExit("密码不能为空")
    if confirm:
        second = getpass.getpass("再次输入确认: ")
        if first != second:
            raise SystemExit("两次输入不一致，未生成任何内容")
    return first


def cmd_generate(user: str) -> int:
    print("=" * 58)
    print("设置账号登录密码")
    print("=" * 58)
    print(f"账号名: {user}")
    print("密码只在本终端输入，不会被保存为明文；输出的是 scrypt 哈希。\n")
    password = _read_password("请输入密码: ", confirm=True)
    try:
        digest = make_password_hash(password)
    except PasswordHashError as exc:
        raise SystemExit(f"生成失败：{exc}") from exc
    print()
    print("生成成功。把下面两行追加到环境变量文件：")
    print()
    print(f"WORKSPACE_USER={user}")
    print(f"WORKSPACE_PASSWORD_HASH={digest}")
    print()
    print("位置：")
    print(f"  本地开发: {PROJECT / '.env'}")
    print("  服务器:   /etc/shilie/workspace.env  然后 systemctl restart shilie")
    print()
    print("改完刷新登录页即可用账号密码登录；令牌登录仍可作为备用。")
    return 0


def cmd_check() -> int:
    stored = (input("粘贴 WORKSPACE_PASSWORD_HASH 值: ") or "").strip()
    if not stored:
        raise SystemExit("未提供哈希")
    password = _read_password("输入要验证的密码: ", confirm=False)
    print("匹配" if verify_password(password, stored) else "不匹配")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="luojiee", help="账号名（默认 luojiee）")
    parser.add_argument("--check", action="store_true", help="验证一个密码与哈希是否匹配")
    args = parser.parse_args()
    if args.check:
        return cmd_check()
    return cmd_generate(args.user)


if __name__ == "__main__":
    raise SystemExit(main())
