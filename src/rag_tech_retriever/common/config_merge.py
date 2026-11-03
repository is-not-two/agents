"""部署配置合并：保留运维覆盖，同时补齐发布包新增键。

部署脚本会把共享目录 ``/var/lib/shilie/config`` 覆盖到发布包的 ``config/``。
纯覆盖会导致发布包新增的配置键（例如 ``mcp.yaml`` 新增的 ``knowledge_search``）
在服务器上永久缺失，形成静默的配置漂移。本模块改为「深合并」：

- 运维在共享目录里的既有取值优先，不被发布包覆盖；
- 发布包中存在、共享目录缺失的键自动补齐；
- 只有共享目录才有的文件继续保留（例如运维自行添加的配置）。

实现说明：合并后写回发布包目录（不修改共享目录），因此每次部署都从
「共享覆盖 + 发布包默认」重新计算，结果确定可复现。YAML/JSON 会因重新
序列化丢失注释，这是补齐键能力的已知代价；需要保留注释的配置请放在共享
目录并由运维维护。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

MERGEABLE = {".yaml", ".yml", ".json"}


def deep_merge(default: dict[str, Any], override: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """把 ``override`` 合并到 ``default``，返回合并结果与补齐的键路径。"""
    merged: dict[str, Any] = dict(default)
    added: list[str] = []
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key], nested = deep_merge(merged[key], value)
            added.extend(f"{key}.{path}" for path in nested)
        else:
            merged[key] = value
    for key in default:
        if key not in override:
            added.append(key)
    return merged, added


def _load(path: Path) -> dict[str, Any]:
    """读取 YAML/JSON；空文件按空映射处理。"""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text) if text.strip() else {}
    else:
        data = yaml.safe_load(text) if text.strip() else {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TypeError(f"配置文件顶层必须是映射：{path}")
    return data


def _dump(path: Path, data: dict[str, Any]) -> None:
    """按扩展名写回，保持 Unicode 与键顺序。"""
    if path.suffix == ".json":
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    else:
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")


def merge_directory(package: Path, persistent: Path, dest: Path) -> list[dict[str, Any]]:
    """把共享配置合并进发布包目录，返回每个文件的补齐记录。

    ``dest`` 通常等于 ``package``；先读取发布包默认值再写回，避免边读边写。
    """
    package_files = {path.name for path in package.iterdir() if path.is_file()}
    results: list[dict[str, Any]] = []
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(package.iterdir()):
        if not path.is_file():
            continue
        target = dest / path.name
        source = persistent / path.name
        if source.is_file() and path.suffix.lower() in MERGEABLE:
            merged, added = deep_merge(_load(path), _load(source))
            _dump(target, merged)
            results.append({"file": path.name, "added": added})
        elif source.is_file():
            # 非合并格式：共享目录版本优先。
            if target.resolve() != source.resolve():
                shutil.copy2(source, target)
            results.append({"file": path.name, "added": [], "kept": True})
        elif target.resolve() != path.resolve():
            shutil.copy2(path, target)
    # 共享目录独有的文件继续保留（运维自行新增的配置）。
    if persistent.is_dir():
        for path in sorted(persistent.iterdir()):
            if path.is_file() and path.name not in package_files:
                target = dest / path.name
                if target.resolve() != path.resolve():
                    shutil.copy2(path, target)
                results.append({"file": path.name, "added": [], "kept": True})
    return results
