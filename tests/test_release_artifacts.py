"""Pure-local release determinism, no-clobber publication and failure compensation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from rag_tech_retriever.common.release_manifest import source_manifest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def package():
    """Load the script without invoking its command-line entrypoint."""
    spec = importlib.util.spec_from_file_location("release_artifact_tests", ROOT / "scripts/release_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release(tmp_path):
    """Use only synthetic source and gate proof; no database or real configuration."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_bytes(b"print('accepted')\n")
    report = tmp_path / "gate.json"
    report.write_text(json.dumps({"schema": 1, "level": "full", "passed": True,
                                  "source_manifest": source_manifest(tmp_path)}), encoding="utf-8")
    return tmp_path, report, tmp_path / "artifacts/release.zip"


def checksum(output: Path) -> Path:
    """Return the existing public checksum naming convention."""
    return output.with_suffix(output.suffix + ".sha256")


def assert_no_artifacts(output: Path) -> None:
    """A failed attempt must not leave its outputs or staging files."""
    assert not os.path.lexists(output)
    assert not os.path.lexists(checksum(output))
    assert not output.parent.exists() or list(output.parent.iterdir()) == []


def test_same_source_and_report_ignore_clock_and_zip_metadata(package, release, monkeypatch):
    root, report, first = release
    second = root / "second/release.zip"
    monkeypatch.setattr(zipfile.time, "localtime", lambda *args: (2020, 2, 3, 4, 5, 6, 0, 0, -1))
    one = package.build(root, report, first)
    monkeypatch.setattr(zipfile.time, "localtime", lambda *args: (2030, 8, 9, 10, 11, 12, 0, 0, -1))
    two = package.build(root, report, second)
    assert first.read_bytes() == second.read_bytes()
    assert one == two
    assert checksum(first).read_bytes() == checksum(second).read_bytes()
    assert one["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert checksum(first).read_bytes() == (one["sha256"] + "  release.zip\n").encode("ascii")
    with zipfile.ZipFile(first) as archive:
        assert archive.testzip() is None
        assert archive.comment == b""
        assert archive.namelist() == ["src/app.py", "RELEASE-MANIFEST.json"]
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.create_system == 3
            assert info.external_attr >> 16 == stat.S_IFREG | 0o644
            assert info.compress_type == zipfile.ZIP_DEFLATED
            assert info.extra == info.comment == b""


def test_chinese_output_name_uses_utf8_checksum(package, release):
    root, report, output = release
    output = output.with_name("时列 发布.zip")
    result = package.build(root, report, output)
    assert result["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert checksum(output).read_bytes() == (
        result["sha256"] + "  时列 发布.zip\n").encode("utf-8")
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
    assert set(output.parent.iterdir()) == {output, checksum(output)}


@pytest.mark.parametrize("role", ["zip", "sha"])
@pytest.mark.parametrize("kind", ["file", "directory", "broken_symlink"])
def test_preexisting_objects_are_never_overwritten(package, release, role, kind):
    root, report, output = release
    output.parent.mkdir()
    target = output if role == "zip" else checksum(output)
    if kind == "file":
        target.write_bytes(b"PREEXISTING")
    elif kind == "directory":
        target.mkdir()
    else:
        try:
            target.symlink_to("missing-target")
        except OSError as exc:
            if os.name == "nt" and exc.winerror == 1314:
                pytest.skip("Windows symlink creation requires privilege")
            raise
    before = target.lstat()
    with pytest.raises((OSError, ValueError)):
        package.build(root, report, output)
    after = target.lstat()
    assert (before.st_dev, before.st_ino, before.st_mode) == (after.st_dev, after.st_ino, after.st_mode)
    if kind == "file":
        assert target.read_bytes() == b"PREEXISTING"
    elif kind == "broken_symlink":
        assert target.is_symlink() and os.readlink(target) == "missing-target"
    assert set(output.parent.iterdir()) == {target}


@pytest.mark.parametrize("role", ["zip", "sha"])
def test_collision_at_atomic_publication_preserves_the_winner(package, release, monkeypatch, role):
    root, report, output = release
    target = output if role == "zip" else checksum(output)
    real_link = os.link

    def race(source, destination, *args, **kwargs):
        if Path(destination) == target:
            target.write_bytes(b"OTHER_PUBLISHER")
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(OSError):
        package.build(root, report, output)
    assert target.read_bytes() == b"OTHER_PUBLISHER"
    assert set(output.parent.iterdir()) == {target}


def test_sha_publish_failure_removes_only_our_zip(package, release, monkeypatch):
    root, report, output = release
    real_link = os.link

    def fail_sha(source, destination, *args, **kwargs):
        if Path(destination) == checksum(output):
            assert output.is_file()
            raise OSError("injected checksum publication failure")
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", fail_sha)
    with pytest.raises(OSError, match="injected checksum"):
        package.build(root, report, output)
    assert_no_artifacts(output)


@pytest.mark.parametrize("replacement", ["file", "symlink_to_our_staging"])
def test_sha_failure_does_not_delete_a_replacement_zip(package, release, monkeypatch, replacement):
    root, report, output = release
    real_link = os.link
    staged_zip = None

    def replace_before_sha(source, destination, *args, **kwargs):
        nonlocal staged_zip
        if Path(destination) == output:
            staged_zip = Path(source)
        if Path(destination) == checksum(output):
            output.unlink()
            if replacement == "file":
                output.write_bytes(b"REPLACEMENT")
            else:
                try:
                    output.symlink_to(staged_zip)
                except OSError as exc:
                    if os.name == "nt" and exc.winerror == 1314:
                        pytest.skip("Windows symlink creation requires privilege")
                    raise
            raise OSError("injected checksum failure after replacement")
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", replace_before_sha)
    with pytest.raises(OSError, match="injected checksum"):
        package.build(root, report, output)
    if replacement == "file":
        assert output.read_bytes() == b"REPLACEMENT"
    else:
        assert output.is_symlink()
    assert set(output.parent.iterdir()) == {output}


@pytest.mark.parametrize("mutation", ["change", "add"])
def test_source_mutation_while_archiving_blocks_publication(package, release, monkeypatch, mutation):
    root, report, output = release
    real_write = zipfile.ZipFile.writestr

    def mutate(archive, name, data, *args, **kwargs):
        result = real_write(archive, name, data, *args, **kwargs)
        if (name.filename if isinstance(name, zipfile.ZipInfo) else name) == "src/app.py":
            path = root / ("src/app.py" if mutation == "change" else "src/added.py")
            path.write_bytes(b"CHANGED_DURING_BUILD\n")
        return result

    monkeypatch.setattr(zipfile.ZipFile, "writestr", mutate)
    with pytest.raises(ValueError, match="发布源发生变化"):
        package.build(root, report, output)
    assert_no_artifacts(output)


def test_source_mutation_after_initial_manifest_blocks_publication(package, release, monkeypatch):
    root, report, output = release
    original = package.source_manifest

    def mutate_after_snapshot(path):
        manifest = original(path)
        (root / "src/app.py").write_bytes(b"CHANGED_BEFORE_READ\n")
        return manifest

    monkeypatch.setattr(package, "source_manifest", mutate_after_snapshot)
    with pytest.raises(ValueError, match="发布源发生变化"):
        package.build(root, report, output)
    assert_no_artifacts(output)


def test_archive_write_failure_cleans_staging(package, release, monkeypatch):
    root, report, output = release

    def fail(*args, **kwargs):
        raise OSError("injected ZIP write failure")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", fail)
    with pytest.raises(OSError, match="injected ZIP"):
        package.build(root, report, output)
    assert_no_artifacts(output)


def test_source_mutation_after_sha_publication_removes_both_outputs(package, release, monkeypatch):
    root, report, output = release
    real_link = os.link

    def mutate_after_sha(source, destination, *args, **kwargs):
        result = real_link(source, destination, *args, **kwargs)
        if Path(destination) == checksum(output):
            assert output.is_file() and checksum(output).is_file()
            (root / "src/app.py").write_bytes(b"CHANGED_AFTER_PUBLICATION\n")
        return result

    monkeypatch.setattr(os, "link", mutate_after_sha)
    with pytest.raises(ValueError, match="发布源发生变化"):
        package.build(root, report, output)
    assert_no_artifacts(output)


@pytest.mark.parametrize("failing_call", [1, 2])
def test_staging_flush_failure_never_publishes(package, release, monkeypatch, failing_call):
    root, report, output = release
    real_fsync = os.fsync
    calls = 0

    def fail_flush(descriptor):
        nonlocal calls
        calls += 1
        if calls == failing_call:
            raise OSError("injected staging flush failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_flush)
    with pytest.raises(OSError, match="injected staging flush"):
        package.build(root, report, output)
    assert_no_artifacts(output)


def test_checksum_staging_write_failure_never_publishes(package, release, monkeypatch):
    root, report, output = release
    real_temporary = package.tempfile.NamedTemporaryFile

    def fail_write(*args, **kwargs):
        raise OSError("injected checksum staging write failure")

    def temporary(*args, **kwargs):
        stream = real_temporary(*args, **kwargs)
        if kwargs.get("prefix") == ".release-sha-":
            stream.write = fail_write
        return stream

    monkeypatch.setattr(package.tempfile, "NamedTemporaryFile", temporary)
    with pytest.raises(OSError, match="injected checksum staging"):
        package.build(root, report, output)
    assert_no_artifacts(output)


def test_unsupported_hardlinks_fail_closed(package, release, monkeypatch):
    root, report, output = release

    def unsupported(*args, **kwargs):
        raise OSError("hardlinks unavailable")

    monkeypatch.setattr(os, "link", unsupported)
    with pytest.raises(OSError, match="hardlinks unavailable"):
        package.build(root, report, output)
    assert_no_artifacts(output)
