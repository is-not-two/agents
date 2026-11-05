"""Build an isolated wheel and verify runtime static files, without network or a database."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

SUFFIXES = {".html", ".css", ".js", ".svg", ".png", ".webp", ".jpg", ".jpeg",
            ".avif", ".mp4", ".webm", ".ico", ".woff", ".woff2"}


def expected_assets(project: Path) -> dict[str, str]:
    """Return packaged runtime paths and exact source hashes; omit declared source-only files."""
    config = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    exclude = config.get("tool", {}).get("setuptools", {}).get("exclude-package-data", {})
    patterns = exclude.get("rag_tech_retriever", []) + exclude.get("*", [])
    package = project / "src" / "rag_tech_retriever"
    result = {}
    for path in sorted((package / "api" / "static").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        relative = path.relative_to(package).as_posix()
        # Excluding a runtime asset in pyproject must not also silence this gate.
        # Only the existing editable/source-only materials may be omitted deliberately.
        if "css_sources" in path.parts or "_archived" in path.parts:
            continue
        if (relative == "api/static/shilie/planning-mist.png"
                and any(fnmatch.fnmatchcase(relative, p) for p in patterns)):
            continue
        if path.is_symlink():
            raise ValueError(f"Runtime asset is a symlink: {relative}")
        result[f"rag_tech_retriever/{relative}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        raise ValueError("No runtime assets found; refusing an empty green check")
    return result


def verify_wheel(project: Path, wheel: Path) -> tuple[list[str], list[str]]:
    """Detect omitted files, duplicates and byte changes in the actual archive."""
    expected = expected_assets(project)
    missing, changed = [], []
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for name, digest in expected.items():
            if name not in names:
                missing.append(name)
            elif names.count(name) != 1 or hashlib.sha256(archive.read(name)).hexdigest() != digest:
                changed.append(name)
    return missing, changed


def build_and_verify(project: Path) -> tuple[list[str], list[str]]:
    """Never build in the checkout, install dependencies or invoke a remote package index."""
    with tempfile.TemporaryDirectory(prefix="shilie-wheel-gate-") as name:
        root = Path(name)
        stage = root / "source"
        stage.mkdir()
        for filename in ("pyproject.toml", "README.md"):
            shutil.copy2(project / filename, stage / filename)
        shutil.copytree(project / "src", stage / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        command = [sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
                   "--no-build-isolation", "--no-cache-dir", str(stage), "-w", str(root / "dist")]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=180, check=False)
        if result.returncode:
            raise RuntimeError("Isolated wheel build failed:\n" + (result.stdout + result.stderr)[-3000:])
        wheels = list((root / "dist").glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("Expected exactly one wheel")
        return verify_wheel(project, wheels[0])


def main(argv: list[str] | None = None) -> int:
    """Print a compact release gate result with a meaningful exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--build", action="store_true")
    choice.add_argument("--wheel", type=Path)
    args = parser.parse_args(argv)
    try:
        missing, changed = (build_and_verify(args.project) if args.build else
                            verify_wheel(args.project, args.wheel))
        for name in missing:
            print("MISSING " + name)
        for name in changed:
            print("MISMATCH " + name)
        if missing or changed:
            print(f"WHEEL_ASSETS_FAILED missing={len(missing)} changed={len(changed)}")
            return 1
        print(f"WHEEL_ASSETS_PASSED files={len(expected_assets(args.project))}")
        return 0
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        print(f"WHEEL_ASSETS_ERROR {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
