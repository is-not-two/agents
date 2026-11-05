"""Isolated cache-version regression cases, no external services."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_static_version.py"
spec = importlib.util.spec_from_file_location("candidate_static_version", SCRIPT)
gate = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(gate)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    version = tmp_path / "static-version.txt"
    version.write_text("115\n", encoding="ascii")
    (static / "index.html").write_text('<script src="/static/shilie/app.js?v=115"></script>', encoding="utf-8")
    (static / "app.js").write_text('import "./feature.js?v=115";\n', encoding="utf-8")
    (static / "feature.js").write_text("export const value=1;\n", encoding="utf-8")
    monkeypatch.setattr(gate, "STATIC", static)
    monkeypatch.setattr(gate, "VERSION", version)
    return static, version


def test_valid_and_comments_strings_regex_do_not_count(sample):
    static, _ = sample
    (static / "app.js").write_text(
        '''// import "./comment.js"\nconst t = "import './text.js'";\n'''
        '''const r = /[&<>"']/g;\nimport {x} from "./feature.js?v=115";\n''', encoding="utf-8")
    assert gate.check("115") == []


@pytest.mark.parametrize("statement", [
    'import "./feature.js";', 'import {x} from "./feature.js";',
    'export {x} from "./feature.js";', 'import("./feature.js");',
    'const x = `${import("./feature.js")}`;',
])
def test_unversioned_import_is_rejected(sample, statement):
    static, _ = sample
    (static / "app.js").write_text(statement, encoding="utf-8")
    assert any("expected v=115" in x for x in gate.check("115"))


def test_nonliteral_dynamic_import_is_rejected(sample):
    static, _ = sample
    (static / "app.js").write_text("import(moduleName);", encoding="utf-8")
    assert any("non-literal" in x for x in gate.check("115"))


def test_external_import_and_css_import_rejected(sample):
    static, _ = sample
    (static / "app.js").write_text('import "https://example.invalid/a.js?v=115";', encoding="utf-8")
    (static / "app.css").write_text('@import "other.css";', encoding="utf-8")
    problems = gate.check("115")
    assert any("external" in x for x in problems)
    assert any("@import" in x for x in problems)


def test_bump_changes_only_refs_not_unrelated_text(sample, monkeypatch):
    static, version = sample
    app = static / "app.js"
    app.write_text('const label="note ?v=115";\nimport "./feature.js?v=115";\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_static_version.py", "--set", "116"])
    assert gate.main() == 0
    assert '"note ?v=115"' in app.read_text(encoding="utf-8")
    assert '"./feature.js?v=116"' in app.read_text(encoding="utf-8")
    assert version.read_text(encoding="ascii") == "116\n"
    assert gate.check("116") == []


def test_bump_refuses_ambiguous_literal_without_modifying_anything(sample, monkeypatch):
    static, version = sample
    app = static / "app.js"
    app.write_text('const copy="./feature.js?v=115";\nimport "./feature.js?v=115";\n', encoding="utf-8")
    before = {p: p.read_bytes() for p in (static / "index.html", app, version)}
    monkeypatch.setattr(sys, "argv", ["check_static_version.py", "--set", "116"])
    assert gate.main() == 1
    assert all(p.read_bytes() == contents for p, contents in before.items())
