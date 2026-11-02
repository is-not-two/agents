"""Offline provenance contract and adversarial filesystem/metadata cases."""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_provenance", Path(__file__).resolve().parents[1] / "scripts/release_provenance.py"
)
assert SPEC and SPEC.loader
provenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provenance)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A tiny project with private URL requirements and irrelevant installed metadata."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="example-project"\nversion="1.0"\n'
        'dependencies=["Alpha>=1; python_version > \'3.9\'"]\n'
        '[project.optional-dependencies]\n'
        'web=["Beta @ https://user:SECRET@example.invalid/beta.whl"]\n'
        'dev=["Unrelated"]\n', encoding="utf-8"
    )
    called = []

    def distribution(name):
        called.append(name)
        if name == "example-project":
            raise provenance.metadata.PackageNotFoundError(name)
        return SimpleNamespace(version={"alpha": "1.2.0", "beta": "2.0+cpu"}[name])

    monkeypatch.setattr(provenance.metadata, "distribution", distribution)
    return tmp_path, called


def test_default_is_deterministic_path_free_and_direct_only(project, monkeypatch):
    root, called = project
    monkeypatch.setenv("LLM_API_KEY", "SECRET_API_KEY")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:SECRET@localhost/db")
    before = sorted(root.iterdir())
    first = provenance.build_report(root)
    second = provenance.build_report(root)
    assert first == second
    assert sorted(root.iterdir()) == before
    assert first["schema"] == provenance.SCHEMA and first["version"] == 1
    content = first["content"]
    assert first["content_sha256"] == hashlib.sha256(
        provenance.canonical_json(content)).hexdigest()
    assert content["project"]["sha256"] == hashlib.sha256(
        (root / "pyproject.toml").read_bytes()).hexdigest()
    assert content["dependencies"]["selected_extras"] == ["web"]
    assert content["dependencies"]["markers_evaluated"] is False
    assert content["dependencies"]["packages"] == [
        {"name": "alpha", "installed": True, "version": "1.2.0"},
        {"name": "beta", "installed": True, "version": "2.0+cpu"},
        {"name": "example-project", "installed": False, "version": None},
    ]
    assert set(called) == {"alpha", "beta", "example-project"}
    assert content["model"]["mode"] == "not_requested"
    assert content["reproducibility"]["classification"] == "provenance_not_lock"
    assert content["reproducibility"]["linux_cpu_lock"] == "not_built_or_validated"
    rendered = json.dumps(first)
    for forbidden in ("SECRET", "https://", str(root), str(Path.home()), sys.executable):
        assert forbidden not in rendered


def test_timestamp_does_not_change_content_hash(project):
    root, _ = project
    first = provenance.build_report(root)
    timed = provenance.build_report(root, timestamp=True)
    assert first["content_sha256"] == timed["content_sha256"]
    assert "observed_at_utc" not in first and "+00:00" in timed["observed_at_utc"]


def test_base_only_and_unknown_extra(project):
    root, _ = project
    assert provenance.build_report(root, extras=[])["content"]["dependencies"][
        "selected_extras"] == []
    with pytest.raises(provenance.ProvenanceError, match="unknown_or_invalid_extra"):
        provenance.build_report(root, extras=["missing"])


def test_tomli_backport_when_stdlib_parser_is_missing(project, monkeypatch):
    """Exercise the Python 3.10 import route without changing the running interpreter."""
    try:
        import tomllib as parser
    except ImportError:
        import tomli as parser
    original_import = builtins.__import__
    calls = []

    def import_parser(name, *args, **kwargs):
        if name == "tomllib":
            raise ModuleNotFoundError("tomllib unavailable", name=name)
        if name == "tomli":
            calls.append(name)
            return parser
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_parser)
    assert provenance.project_inventory(project[0])["project"]["name"] == "example-project"
    assert calls == ["tomli"]


def test_missing_toml_parsers_has_actionable_error(project, monkeypatch):
    original_import = builtins.__import__

    def import_parser(name, *args, **kwargs):
        if name in {"tomllib", "tomli"}:
            raise ModuleNotFoundError("TOML parser unavailable", name=name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_parser)
    with pytest.raises(provenance.ProvenanceError,
                       match="toml_parser_missing_install_web_or_dev_extra"):
        provenance.project_inventory(project[0])


@pytest.mark.parametrize("value", ["pgvector:pg16", "sha256:abc", "", "sha256:" + "A" * 64,
                                  "https://registry.invalid/image@sha256:" + "1" * 64])
def test_image_tag_or_reference_is_not_digest(project, value):
    with pytest.raises(provenance.ProvenanceError, match="requires_sha256_not_tag"):
        provenance.build_report(project[0], db_image_digest=value)


def test_explicit_image_digest_is_declared_not_runtime_verified(project):
    digest = "sha256:" + "a" * 64
    database = provenance.build_report(project[0], db_image_digest=digest)["content"]["database"]
    assert database == {"image_digest": digest,
                        "verification": "operator_declared_not_runtime_verified"}


def test_explicit_model_selection_hashes_bytes_not_mtime(project):
    root, _ = project
    model = root / "model"
    model.mkdir()
    selected = model / "config.json"
    selected.write_bytes(b'{"hidden_size":768}')
    (model / ".env").write_text("API_KEY=SECRET", encoding="utf-8")
    (model / "huge.bin").write_bytes(b"not selected")
    first = provenance.build_report(root, model_root=model, model_files=["config.json"])
    file_info = first["content"]["model"]["files"]
    assert file_info == [{"path": "config.json", "size_bytes": selected.stat().st_size,
                          "sha256": hashlib.sha256(selected.read_bytes()).hexdigest()}]
    os.utime(selected, (1000, 1000))
    second = provenance.build_report(root, model_root=model, model_files=["config.json"])
    assert first["content_sha256"] == second["content_sha256"]
    assert "mtime" not in json.dumps(first)
    selected.write_bytes(b'{"hidden_size":769}')
    assert provenance.build_report(root, model_root=model, model_files=["config.json"])[
        "content_sha256"] != first["content_sha256"]


@pytest.mark.parametrize("name", [".env", "token.txt", "credentials.json", "../config.json",
                                 "/config.json", "C:/config.json", "1_Pooling/../config.json",
                                 "1_Pooling\\config.json", "secret/config.json", "./config.json",
                                 "config.json/", "1_Pooling//config.json"])
def test_model_paths_fail_closed(project, name):
    with pytest.raises(provenance.ProvenanceError):
        provenance.build_report(project[0], model_root=project[0], model_files=[name])


def test_model_no_implicit_scan_missing_root_and_budget(project):
    root, _ = project
    (root / "config.json").write_bytes(b"12345")
    with pytest.raises(provenance.ProvenanceError, match="explicit_model_files_required"):
        provenance.build_report(root, model_root=root)
    with pytest.raises(provenance.ProvenanceError, match="model_root_required"):
        provenance.build_report(root, model_files=["config.json"])
    with pytest.raises(provenance.ProvenanceError, match="model_byte_limit_exceeded"):
        provenance.build_report(root, model_root=root, model_files=["config.json"],
                                model_max_bytes=4)
    with pytest.raises(provenance.ProvenanceError, match="duplicate_model_file"):
        provenance.build_report(root, model_root=root,
                                model_files=["config.json", "config.json"])


@pytest.mark.parametrize("limit", [0, -1, True, provenance.MAX_MODEL_BYTES + 1])
def test_invalid_model_budget(project, limit):
    with pytest.raises(provenance.ProvenanceError, match="invalid_model_byte_limit"):
        provenance.build_report(project[0], model_max_bytes=limit)


def _manifest(root, entry=None):
    path = root / "model-hashes.json"
    path.write_text(json.dumps({"schema": provenance.MANIFEST_SCHEMA, "version": 1,
                               "files": [entry or {"path": "config.json",
                                                   "sha256": "a" * 64, "size_bytes": 12}]}),
                    encoding="utf-8")
    return path


def test_manifest_is_declaration_not_observed_files(project):
    root, _ = project
    path = _manifest(root)
    report = provenance.build_report(root, model_manifest=path)
    assert not (root / "config.json").exists()
    model = report["content"]["model"]
    assert model["verification"] == "declared_not_verified"
    assert model["manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "size_bytes" in model["files"][0]
    with pytest.raises(provenance.ProvenanceError, match="mutually_exclusive"):
        provenance.build_report(root, model_manifest=path, model_root=root)


@pytest.mark.parametrize("entry", [
    {"path": "config.json", "sha256": "not-a-hash", "size_bytes": 1},
    {"path": ".env", "sha256": "a" * 64, "size_bytes": 1},
    {"path": "config.json", "sha256": "a" * 64, "size_bytes": True},
    {"path": "config.json", "sha256": "a" * 64, "size_bytes": -1},
    {"path": "config.json", "sha256": "a" * 64, "size_bytes": 1, "token": "SECRET"},
])
def test_manifest_rejects_invalid_or_extra_fields(project, entry):
    with pytest.raises(provenance.ProvenanceError):
        provenance.build_report(project[0], model_manifest=_manifest(project[0], entry))


def test_manifest_schema_budget_and_duplicates(project):
    root, _ = project
    path = _manifest(root)
    data = json.loads(path.read_text())
    with pytest.raises(provenance.ProvenanceError, match="model_byte_limit_exceeded"):
        provenance.build_report(root, model_manifest=path, model_max_bytes=1)
    data["files"] *= 2
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="duplicate_model_file"):
        provenance.build_report(root, model_manifest=path)
    data["version"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="invalid_model_manifest_schema"):
        provenance.build_report(root, model_manifest=path)


def test_hardlinked_model_file_is_rejected(project):
    root, _ = project
    source = root / ".env"
    source.write_bytes(b"SECRET")
    os.link(source, root / "config.json")
    with pytest.raises(provenance.ProvenanceError, match="single_link_regular_file_required"):
        provenance.build_report(root, model_root=root, model_files=["config.json"])


def test_symlink_or_windows_junction_is_rejected(project):
    root, _ = project
    actual = root / "actual"
    actual.mkdir()
    (actual / "config.json").write_bytes(b"{}")
    linked = root / "link"
    if os.name == "nt":
        import subprocess
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(actual)],
                                capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
    else:
        linked.symlink_to(actual, target_is_directory=True)
    try:
        with pytest.raises(provenance.ProvenanceError, match="links_not_allowed"):
            provenance.build_report(root, model_root=linked, model_files=["config.json"])
        with pytest.raises(provenance.ProvenanceError, match="links_not_allowed"):
            provenance.write_report({}, linked / "report.json", root)
    finally:
        if os.name == "nt":
            linked.rmdir()
        else:
            linked.unlink()


def test_output_native_json_no_overwrite_and_no_external_write(project):
    root, _ = project
    report = provenance.build_report(root)
    output = root / "report.json"
    provenance.write_report(report, output, root)
    original = output.read_bytes()
    assert json.loads(original) == report
    with pytest.raises(provenance.ProvenanceError, match="output_already_exists"):
        provenance.write_report({"changed": True}, output, root)
    assert output.read_bytes() == original
    external = root.parent / "outside.json"
    with pytest.raises(provenance.ProvenanceError, match="output_must_stay_inside_project"):
        provenance.write_report(report, external, root)
    assert not external.exists()
    with pytest.raises(provenance.ProvenanceError, match="json_suffix"):
        provenance.write_report(report, root / "report.txt", root)
    with pytest.raises(provenance.ProvenanceError, match="existing_directory"):
        provenance.write_report(report, root / "missing" / "report.json", root)


def test_failed_output_write_removes_only_created_partial_file(project, monkeypatch):
    root, _ = project

    def failed_fsync(fd):
        raise OSError(5, "simulated disk write failure")

    monkeypatch.setattr(provenance.os, "fsync", failed_fsync)
    with pytest.raises(OSError):
        provenance.write_report({"ok": True}, root / "partial.json", root)
    assert not (root / "partial.json").exists()


def test_installed_version_cannot_inject_url_or_path(project, monkeypatch):
    monkeypatch.setattr(provenance.metadata, "distribution",
                        lambda _: SimpleNamespace(version="https://SECRET@example.invalid"))
    with pytest.raises(provenance.ProvenanceError, match="invalid_distribution_version"):
        provenance.build_report(project[0])


def test_invalid_pyproject_rejected_without_echoing_secret(project):
    root, _ = project
    (root / "pyproject.toml").write_text('[project]\nname="SECRET/path"\nversion="1"\n',
                                         encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="invalid_distribution_name") as error:
        provenance.build_report(root)
    assert "SECRET" not in str(error.value)


def test_cli_default_stdout_only_and_sanitized_error(project, monkeypatch, capsys):
    root, _ = project
    monkeypatch.setattr(provenance, "__file__", str(root / "scripts/release_provenance.py"))
    before = sorted(root.iterdir())
    assert provenance.main([]) == 0
    result = capsys.readouterr()
    assert json.loads(result.out)["schema"] == provenance.SCHEMA
    assert result.err == "" and sorted(root.iterdir()) == before
    assert provenance.main(["--db-image-digest", "pgvector:pg16"]) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert result.err == "provenance_error: db_image_digest_requires_sha256_not_tag\n"


def test_cli_io_failure_is_path_free(project, monkeypatch, capsys):
    root, _ = project
    monkeypatch.setattr(provenance, "__file__", str(root / "scripts/release_provenance.py"))
    assert provenance.main(["--model-manifest", str(root / "SECRET-nonexistent.json")]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "provenance_io_error: errno=2\n"
