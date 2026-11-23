"""Refuse accidental reintroduction of the retired frontend."""
from pathlib import Path

import pytest


@pytest.mark.parametrize("relative", ("src/rag_tech_retriever/api/static/shilie", "scripts/verify-ui.mjs"))
def test_retired_frontend_cannot_pass_source_gate(tmp_path, monkeypatch, relative):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from check_vue_candidate import check_source_layout

    (tmp_path / "src/rag_tech_retriever/api/static/vue").mkdir(parents=True)
    check_source_layout(tmp_path)
    old = tmp_path / relative
    old.parent.mkdir(parents=True, exist_ok=True)
    if old.suffix:
        old.write_text("// retired", encoding="utf-8")
    else:
        old.mkdir()
    with pytest.raises(RuntimeError, match="旧前端残留"):
        check_source_layout(tmp_path)
