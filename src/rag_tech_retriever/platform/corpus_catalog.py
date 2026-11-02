"""Server-owned corpus allowlist; explicit selection never falls back to another domain."""

from copy import deepcopy
from pathlib import Path

from rag_tech_retriever.common.config_loader import ConfigLoader, load_yaml_mapping
from rag_tech_retriever.domains.life_planning import DomainError

DEFAULT = {"default": "tech_doc", "allowed": ["tech_doc"], "corpora": {
    "tech_doc": {"label": "本机技术语料", "path": "data/processed/corpus.jsonl"},
    "public_docs": {"label": "公开技术文档", "path": "data/public/public_docs.bundle.json"}}}


class CorpusCatalog:
    """No browser-supplied file paths, table names or widening of configured namespaces."""

    def __init__(self, root: Path | None = None) -> None:
        self.settings = ConfigLoader.load_default()
        self.root = (root or self.settings.settings_path.parent.parent).resolve()
        path = self.root / "config/corpora.yaml"
        self.explicit = path.exists()
        self.config = load_yaml_mapping(path) if self.explicit else deepcopy(DEFAULT)
        value = self.config
        if (set(value) != {"default", "allowed", "corpora"} or not isinstance(value["allowed"], list)
                or not value["allowed"] or any(not isinstance(k, str) or k not in DEFAULT["corpora"] for k in value["allowed"])
                or not isinstance(value["default"], str) or value["default"] not in value["allowed"]
                or not isinstance(value["corpora"], dict) or set(value["corpora"]) != set(DEFAULT["corpora"])):
            raise DomainError("语料域配置无效，未扩大访问范围")
        for item in value["corpora"].values():
            if (not isinstance(item, dict) or set(item) != {"label", "path"}
                    or any(not isinstance(item[k], str) or not item[k].strip() for k in item)):
                raise DomainError("语料来源必须由管理员配置名称和工作区内路径")
            self._safe_path(item["path"])

    def _safe_path(self, relative: str) -> Path:
        path = self.root / relative
        if Path(relative).is_absolute() or not path.resolve().is_relative_to(self.root):
            raise DomainError("语料路径不能越出工作区")
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != self.root and parent.is_relative_to(self.root)):
            raise DomainError("语料路径不允许符号链接")
        return path

    def select(self, namespace: str | None) -> str:
        """Resolve the default only when omitted; malformed/disabled input fails closed."""
        selected = self.config["default"] if namespace is None else namespace
        if not isinstance(selected, str) or selected not in self.config["allowed"]:
            raise DomainError("该语料域未获服务器授权")
        return selected

    def path(self, namespace: str) -> Path | None:
        self.select(namespace)
        if namespace == "tech_doc" and not self.explicit:
            # Keep historical config/env path semantics, including test resolvers.
            return self.settings.resolve("paths.corpus_jsonl")
        return self._safe_path(self.config["corpora"][namespace]["path"])

    def options(self) -> dict:
        """Return safe labels, not filesystem paths or corpus content."""
        return {"default": self.config["default"], "namespaces": [
            {"id": key, "label": self.config["corpora"][key]["label"],
             "installed": bool(self.path(key) and self.path(key).is_file())}
            for key in dict.fromkeys(self.config["allowed"])]}
