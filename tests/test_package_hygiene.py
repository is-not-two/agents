"""包卫生：不得再出现“只有 docstring、没有实现”的占位模块。

历史上有 10 个空壳模块（agent/rag_graph、agent/tool_executor、common/constants、
common/utils、rag/data_processor/*、rag/retrieval/base_retriever、level_matcher），
它们零引用却出现在结构文档里，容易被误认为能力已存在。此测试钉住该不变式。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import rag_tech_retriever


def _statements_without_docstring(tree: ast.Module) -> list[ast.stmt]:
    """返回模块级语句，剔除单独存在的字符串字面量（即模块 docstring）。"""
    docstring = (
        tree.body[0]
        if tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
        else None
    )
    return [node for node in tree.body if node is not docstring]


def test_package_has_no_docstring_only_modules() -> None:
    """包内所有 .py（空 __init__.py 除外）都必须有实际语句。"""
    root = Path(rag_tech_retriever.__file__).parent
    offenders = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
        and path.name != "__init__.py"
        and not _statements_without_docstring(ast.parse(path.read_text(encoding="utf-8")))
    )
    assert offenders == [], offenders


JUNK_NAMES = re.compile(r"(\.bak(\.|$)|\.tmp$|\.orig$|~$|\.swp$)")


def test_static_assets_have_no_editor_backup_files() -> None:
    """静态目录随 release 发布，编辑器备份/临时文件不应出现在前端资源里。"""
    static = Path(rag_tech_retriever.__file__).parent / "api" / "static"
    offenders = sorted(
        path.relative_to(static).as_posix()
        for path in static.rglob("*")
        if path.is_file() and JUNK_NAMES.search(path.name)
    )
    assert offenders == [], offenders
