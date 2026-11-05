"""Actual archive contents, not source-file presence, determine release completeness."""
from __future__ import annotations

import importlib.util
import warnings
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_wheel_assets.py"
SPEC = importlib.util.spec_from_file_location("wheel_asset_gate", SCRIPT)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def project(tmp_path: Path) -> Path:
    """Create a tiny independent package fixture, never copy user media."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.setuptools.exclude-package-data]\nrag_tech_retriever = ["api/static/shilie/_archived/*"]\n',
        encoding="utf-8",
    )
    folder = tmp_path / "src/rag_tech_retriever/api/static/shilie"
    for name, data in {"index.html": b"<html></html>", "assets/wallpaper/test.mp4": b"video",
                       "assets/wallpaper/test.webp": b"image", "_archived/old.css": b"old",
                       "css_sources/10-base.css": b"source"}.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return tmp_path


def wheel(root: Path, *, missing: bool = False, corrupt: bool = False,
          duplicate: bool = False) -> Path:
    """Use a synthetic wheel so negative tests are deterministic and offline."""
    result = root / "fixture.whl"
    with zipfile.ZipFile(result, "w") as archive:
        for name in GATE.expected_assets(root):
            if missing and name.endswith("test.mp4"):
                continue
            data = (root / "src" / name).read_bytes()
            archive.writestr(name, b"changed" if corrupt and name.endswith("test.webp") else data)
            if duplicate and name.endswith("test.mp4"):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr(name, data)
    return result


def test_nested_runtime_assets_and_source_exclusions(tmp_path: Path) -> None:
    root = project(tmp_path)
    expected = GATE.expected_assets(root)
    assert len(expected) == 3
    assert not any("_archived" in name or "css_sources" in name for name in expected)
    assert GATE.verify_wheel(root, wheel(root)) == ([], [])


def test_missing_video_is_not_green(tmp_path: Path) -> None:
    root = project(tmp_path)
    missing, changed = GATE.verify_wheel(root, wheel(root, missing=True))
    assert len(missing) == 1 and missing[0].endswith("test.mp4") and not changed


@pytest.mark.parametrize("option", ["corrupt", "duplicate"])
def test_modified_or_duplicate_assets_fail(tmp_path: Path, option: str) -> None:
    root = project(tmp_path)
    missing, changed = GATE.verify_wheel(root, wheel(root, **{option: True}))
    assert not missing and len(changed) == 1


def test_empty_static_tree_cannot_pass(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="No runtime assets"):
        GATE.expected_assets(tmp_path)


def test_cli_returns_nonzero_for_missing_assets(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)
    result = wheel(root, missing=True)
    assert GATE.main(["--project", str(root), "--wheel", str(result)]) == 1
    assert "WHEEL_ASSETS_FAILED" in capsys.readouterr().out


def test_runtime_exclusion_cannot_hide_missing_media(tmp_path: Path) -> None:
    root = project(tmp_path)
    config = root / "pyproject.toml"
    config.write_text(config.read_text(encoding="utf-8").replace(
        '["api/static/shilie/_archived/*"]',
        '["api/static/shilie/_archived/*", "api/static/shilie/assets/*"]'), encoding="utf-8")
    missing, changed = GATE.verify_wheel(root, wheel(root, missing=True))
    assert len(missing) == 1 and missing[0].endswith("test.mp4") and not changed
