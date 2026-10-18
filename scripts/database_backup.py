"""完整 PostgreSQL 备份/恢复（含向量与全部版本），二进制不经 PowerShell 文本管道。"""

import argparse
import subprocess
from pathlib import Path

from rag_tech_retriever.common.config_loader import PROJECT_ROOT, ConfigLoader


def main() -> None:
    """backup 真正落盘；restore 默认只列备份，--apply 才事务恢复数据库。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "restore"])
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    cfg = ConfigLoader.load_default()
    prefix = ["docker", "compose", "exec", "-T", "db"]
    connection = [
        "-U",
        str(cfg.env("POSTGRES_USER", "rag")),
        "-d",
        str(cfg.env("POSTGRES_DB", "rag_tech_doc")),
    ]
    if args.command == "backup":
        args.file.parent.mkdir(parents=True, exist_ok=True)
        if args.file.exists():
            parser.error("备份文件已存在，拒绝覆盖")
        temporary = args.file.with_suffix(args.file.suffix + ".tmp")
        with temporary.open("wb") as output:
            result = subprocess.run(
                prefix + ["pg_dump", *connection, "-Fc"],
                check=False,
                stdout=output,
                stderr=subprocess.PIPE,
                cwd=PROJECT_ROOT,
            )
        if result.returncode:
            temporary.unlink(missing_ok=True)
            raise SystemExit("数据库备份失败，请检查容器状态与权限")
        temporary.replace(args.file)
        print(f"备份完成：{args.file.resolve()}（{args.file.stat().st_size} bytes）")
    else:
        with args.file.open("rb") as source:
            command = ["pg_restore", *connection, "--clean", "--if-exists", "--single-transaction"]
            if not args.apply:
                command = ["pg_restore", "--list"]
            result = subprocess.run(prefix + command, check=False, stdin=source, cwd=PROJECT_ROOT)
        if result.returncode:
            raise SystemExit("备份预检/恢复失败")
        if not args.apply:
            print("仅预检；恢复覆盖整个工作台数据库。先做保护备份、停 app，再加 --apply。")


if __name__ == "__main__":
    main()
