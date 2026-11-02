"""配置加载器：yaml 配置 + .env 文件 + 环境变量覆盖。

优先级：环境变量 > .env 文件 > config/settings.yaml；所有取值都带默认值，配置缺失不崩溃
（对齐 Configuration Management 规范）。

用法:
    from rag_tech_retriever.common.config_loader import ConfigLoader

    cfg = ConfigLoader.load_default()
    dim = cfg.get("embedding.dim", 768)          # settings.yaml 的值（可被环境变量覆盖）
    password = cfg.env("POSTGRES_PASSWORD", "")  # 环境变量或 .env
    corpus = cfg.resolve("paths.corpus_jsonl")   # 相对路径解析为项目内绝对路径

阶段：V1 起使用。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(
    os.environ.get("RAG_PROJECT_ROOT", str(Path(__file__).resolve().parents[3]))
).resolve()
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"

#: 环境变量 → 配置路径覆盖映射（环境变量优先，无需改代码即可切换参数）
ENV_OVERRIDES: dict[str, str] = {
    "EMBEDDING_MODEL": "embedding.model_name",
    "EMBEDDING_DIM": "embedding.dim",
    "EMBEDDING_DEVICE": "embedding.device",
    "CHUNKING_MAX_CHARS": "chunking.max_chunk_chars",
    "RETRIEVAL_TOP_K": "retrieval.top_k",
}


class ConfigError(Exception):
    """配置加载或取值失败。"""


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read safe YAML, rejecting duplicate keys instead of silently discarding values."""
    try:
        import yaml
    except ImportError as exc:
        raise ConfigError("未安装 pyyaml") from exc

    class UniqueLoader(yaml.SafeLoader):
        """Local loader: do not mutate PyYAML's global constructors."""

    def mapping(loader, node, deep=False):
        loader.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as exc:
                raise ConfigError("YAML 键必须为标量") from exc
            if duplicate:
                raise ConfigError(f"{path.name}:{key_node.start_mark.line + 1} 重复配置键：{key}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        data = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=UniqueLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"配置文件不可读取或 YAML 格式错误：{path.name}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"配置顶层必须是映射：{path.name}")
    return data


def _coerce(value: str) -> Any:
    """把环境变量字符串转成合适的类型（bool / int / float / str）。"""
    lowered = value.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


class ConfigLoader:
    """配置加载器：settings.yaml + .env + 环境变量三层合并。"""

    def __init__(
        self,
        settings_path: Path = DEFAULT_SETTINGS_PATH,
        env_path: Path = DEFAULT_ENV_PATH,
    ) -> None:
        """初始化并加载配置。

        Args:
            settings_path: settings.yaml 路径。
            env_path: .env 文件路径（不存在时跳过）。
        """
        self.settings_path = Path(settings_path)
        self.env_path = Path(env_path)
        self._dotenv = self._load_env_file()
        self._data = self._load_settings()

    @classmethod
    def load_default(cls) -> ConfigLoader:
        """使用项目默认路径加载配置。"""
        return cls()

    def _load_env_file(self) -> dict[str, str]:
        """解析 .env 文件（KEY=VALUE；# 开头为注释；值可用引号包裹）。"""
        if not self.env_path.is_file():
            return {}
        values: dict[str, str] = {}
        for raw_line in self.env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def _load_settings(self) -> dict[str, Any]:
        """读取 yaml 并应用环境变量覆盖。"""
        if not self.settings_path.is_file():
            raise ConfigError(f"settings.yaml 不存在：{self.settings_path}")
        data = load_yaml_mapping(self.settings_path)
        for env_name, config_path in ENV_OVERRIDES.items():
            raw = self.env(env_name)
            if raw not in (None, ""):
                self._set_path(data, config_path, _coerce(raw))
        return data

    @staticmethod
    def _set_path(data: dict[str, Any], dotted: str, value: Any) -> None:
        """按 "a.b.c" 路径写值，中间层缺失时自动创建。"""
        keys = dotted.split(".")
        node = data
        for key in keys[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[keys[-1]] = value

    def env(self, name: str, default: str | None = None) -> str | None:
        """读取环境变量：进程环境优先，其次 .env 文件。"""
        if name in os.environ:
            return os.environ[name]
        return self._dotenv.get(name, default)

    def get(self, dotted: str, default: Any = None) -> Any:
        """按 "a.b.c" 路径读取配置值，缺失返回默认值。"""
        node: Any = self._data
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def require(self, dotted: str) -> Any:
        """读取必填配置，缺失抛 ConfigError。"""
        value = self.get(dotted, None)
        if value is None:
            raise ConfigError(f"缺少必填配置项：{dotted}")
        return value

    def resolve(self, dotted: str, default: Any = None) -> Path | None:
        """读取相对路径配置并解析为项目内绝对路径。"""
        value = self.get(dotted, default)
        if value is None:
            return None
        return PROJECT_ROOT / str(value)
