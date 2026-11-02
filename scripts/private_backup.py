"""私密数据加密备份：只在本机终端交互输入备份口令，不接受命令行明文密钥。"""

from __future__ import annotations

import argparse
import getpass
import json
import socket
import sys
from pathlib import Path

import yaml

from rag_tech_retriever.common.config_loader import PROJECT_ROOT
from rag_tech_retriever.platform import private_backup as backup
from rag_tech_retriever.platform.record_store import RecordStore, StorageError


def main() -> int:
    """Export/inspect/restore counts; never disclose private content in stdout/errors."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export", "inspect", "restore"])
    parser.add_argument("archive", type=Path)
    parser.add_argument("--confirm", default="", help="恢复时必须为：恢复到空私密区")
    args = parser.parse_args()
    cfg = yaml.safe_load((PROJECT_ROOT / "config/web.yaml").read_text(encoding="utf-8"))["web"]
    try:
        if args.command != "export" and not args.archive.is_file():
            raise ValueError("备份文件不存在")
        if args.command in {"export", "restore"}:
            with socket.socket() as sock:
                sock.settimeout(1)
                host = cfg.get("host", "127.0.0.1")
                host = "127.0.0.1" if host == "0.0.0.0" else host
                if sock.connect_ex((host, cfg.get("port", 8770))) == 0:
                    raise ValueError("请先停止网页服务，并确认没有其他实例写入数据库")
        if args.command == "restore" and args.confirm != "恢复到空私密区":
            raise ValueError("恢复需要 --confirm 恢复到空私密区")
        if not sys.stdin.isatty():
            raise ValueError("请在交互终端中输入备份口令；禁止通过管道传入口令")
        password = getpass.getpass("备份包口令（不是网页私密口令）: ")
        maximum = cfg.get("private_backup_max_bytes", backup.DEFAULT_MAX_BYTES)
        if args.command == "export":
            if password != getpass.getpass("再次输入备份包口令: "):
                raise ValueError("两次备份口令不一致")
            store = RecordStore(cfg["table_prefix"])
            vault = Path(store.config.env("PROJECT_ROOT", str(PROJECT_ROOT))) / "data/local/private-vault.json"
            payload = backup.capture(store, vault)
            backup.write_archive(payload, args.archive.resolve(), password, maximum)
        else:
            payload = backup.read_archive(args.archive, password, maximum)
            if args.command == "restore":
                store = RecordStore(cfg["table_prefix"])
                vault = Path(store.config.env("PROJECT_ROOT", str(PROJECT_ROOT))) / "data/local/private-vault.json"
                store.ensure_schema()
                backup.restore(store, vault, payload)
        print(json.dumps({"status": "ok", "command": args.command,
                          "archive": str(args.archive.resolve()), **backup.summary(payload)},
                         ensure_ascii=False))
        return 0
    except (ValueError, StorageError, OSError, EOFError) as exc:
        # OS exceptions may contain local paths; database causes may contain credentials.
        message = str(exc) if isinstance(exc, (ValueError, StorageError)) else type(exc).__name__
        print(json.dumps({"status": "failed", "reason": message}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
