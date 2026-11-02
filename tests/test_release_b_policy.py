"""Release QA must not silently follow a mutable database image tag."""

import ast
import re
from pathlib import Path


def test_owned_qa_database_image_is_content_pinned():
    """Inspect the literal without starting Docker or importing the QA runner."""
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "scripts/ci_verify.py").read_text(encoding="utf-8"))
    values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "IMAGE" for target in node.targets)]
    assert len(values) == 1
    assert re.fullmatch(r"pgvector/pgvector@sha256:[0-9a-f]{64}", values[0])
