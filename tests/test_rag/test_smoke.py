"""结构冒烟测试：主包可导入、关键目录/文件就位。"""

from pathlib import Path

import rag_tech_retriever


def test_package_importable() -> None:
    """主包可正常导入且带版本号。"""
    assert rag_tech_retriever.__version__ == "0.1.0"


def test_project_layout(project_root: Path) -> None:
    """配置目录与原始语料归档目录已就位。"""
    assert (project_root / "config" / "settings.yaml").is_file()
    assert (project_root / "data" / "raw" / "aihuoke_docs").is_dir()
