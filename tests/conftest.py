"""测试配置与 fixture：项目根路径、语料路径。"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """项目根目录（rag-tech-doc-retriever/）。"""
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def corpus_path(project_root: Path) -> Path:
    """标准语料 corpus.jsonl 路径。"""
    return project_root / "data" / "processed" / "corpus.jsonl"
