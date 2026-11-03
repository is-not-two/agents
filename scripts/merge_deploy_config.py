"""部署时合并共享配置与发布包默认配置。

用法（服务器部署脚本内调用）：
    PYTHONPATH="$DEST/src" "$DEST/.venv/bin/python" "$DEST/scripts/merge_deploy_config.py" \
        --package "$DEST/config" --persistent /var/lib/shilie/config --dest "$DEST/config"

退出码：0=成功并打印补齐键；1=配置格式错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rag_tech_retriever.common.config_merge import merge_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="合并部署配置")
    parser.add_argument("--package", type=Path, required=True, help="发布包默认配置目录")
    parser.add_argument("--persistent", type=Path, required=True, help="服务器共享配置目录")
    parser.add_argument("--dest", type=Path, required=True, help="合并结果写入目录")
    args = parser.parse_args()

    try:
        results = merge_directory(args.package, args.persistent, args.dest)
    except (TypeError, ValueError, OSError) as exc:
        print(f"配置合并失败：{exc}")
        return 1
    for entry in results:
        added = ", ".join(entry["added"]) or "无"
        suffix = "（共享独有，保留）" if entry.get("kept") else ""
        print(f"{entry['file']}: 补齐 {added}{suffix}")
    print("配置合并完成：共享取值优先，发布包新增键已补齐。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
