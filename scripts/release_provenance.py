"""Offline runtime provenance; no installation, network, application import or database access.

Python 3.10 uses the declared Tomli backport; 3.11+ uses the standard-library
TOML parser. The application retains its independent Python requirement.
Reports are evidence, not locks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import stat
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "rag-tech-doc-retriever/release-provenance"
SCHEMA_VERSION = 1
MANIFEST_SCHEMA = "rag-tech-doc-retriever/model-hashes"
DEFAULT_MODEL_MAX_BYTES = 64 * 1024 * 1024
MAX_MODEL_BYTES = 16 * 1024 * 1024 * 1024
MAX_MODEL_FILES = 128
MAX_METADATA_BYTES = 2 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9])?\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MODEL_DIR = re.compile(r"[0-9]+_(?:Pooling|Normalize|Dense|Transformer)\Z")
_MODEL_NAMES = frozenset(
    {
        "config.json", "config_sentence_transformers.json", "modules.json",
        "sentence_bert_config.json", "special_tokens_map.json", "tokenizer.json",
        "tokenizer_config.json", "vocab.txt", "vocab.json", "merges.txt",
        "pytorch_model.bin", "model.safetensors", "sentencepiece.bpe.model",
        "spiece.model", "tokenizer.model", "model.safetensors.index.json",
        "pytorch_model.bin.index.json",
    }
)
_MODEL_SHARD = re.compile(r"(?:model-[0-9]{5}-of-[0-9]{5}\.safetensors|"
                          r"pytorch_model-[0-9]{5}-of-[0-9]{5}\.bin)\Z")


class ProvenanceError(ValueError):
    """Safe, path-free validation error suitable for CLI output."""


def canonical_json(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON, without an observation timestamp."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _normal_name(value: object) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ProvenanceError("invalid_distribution_name")
    return re.sub(r"[-_.]+", "-", value).lower()


def _version(value: object) -> str:
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise ProvenanceError("invalid_distribution_version")
    return value


def _no_links(path: Path) -> None:
    """Reject symlinks/reparse points, including junctions, in existing ancestors."""
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise ProvenanceError("links_not_allowed")


def _regular_stat(path: Path) -> os.stat_result:
    _no_links(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ProvenanceError("single_link_regular_file_required")
    return info


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_size, left.st_mtime_ns) == (
        right.st_dev, right.st_ino, right.st_size, right.st_mtime_ns
    )


def _read_file(path: Path, limit: int) -> bytes:
    """Read bounded metadata from a regular file, checking its identity afterward."""
    before = _regular_stat(path)
    if before.st_size > limit:
        raise ProvenanceError("metadata_size_limit_exceeded")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if not _same_file(before, os.fstat(stream.fileno())):
            raise ProvenanceError("input_changed_during_read")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(data) > limit:
        raise ProvenanceError("metadata_size_limit_exceeded")
    if not _same_file(before, after) or not _same_file(before, _regular_stat(path)):
        raise ProvenanceError("input_changed_during_read")
    return data


def _requirement_name(requirement: object) -> str:
    """Extract only a PEP 508 name; never emit version specifiers, URLs or markers."""
    if not isinstance(requirement, str):
        raise ProvenanceError("invalid_requirement")
    match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)(?=\s|\[|[<>=!~@;]|$)",
                     requirement)
    if match is None:
        raise ProvenanceError("invalid_requirement")
    return _normal_name(match.group(1))


def project_inventory(project_root: Path, extras: Sequence[str] | None = None) -> dict[str, Any]:
    """Hash pyproject and inspect only the declared direct distribution metadata.

    Markers are intentionally not evaluated: this is a declared inventory, not a
    resolver or transitive lock. Metadata paths/direct_url.json are never read.
    """
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError as exc:
            raise ProvenanceError("toml_parser_missing_install_web_or_dev_extra") from exc
    raw = _read_file(project_root / "pyproject.toml", MAX_METADATA_BYTES)
    try:
        project = tomllib.loads(raw.decode("utf-8"))["project"]
        if not isinstance(project, dict):
            raise TypeError
        name = _normal_name(project["name"])
        version = _version(project["version"])
        optional = project.get("optional-dependencies", {})
        dependencies = project.get("dependencies", [])
        if not isinstance(optional, dict) or not isinstance(dependencies, list):
            raise TypeError
        selected = sorted(set(extras if extras is not None else (
            ["web"] if "web" in optional else []
        )))
        for extra in selected:
            _normal_name(extra)
            if extra not in optional or not isinstance(optional[extra], list):
                raise ProvenanceError("unknown_or_invalid_extra")
            dependencies = dependencies + optional[extra]
        names = sorted({name, *(_requirement_name(item) for item in dependencies)})
    except ProvenanceError:
        raise
    except (KeyError, ValueError, TypeError, UnicodeError) as exc:
        raise ProvenanceError("invalid_project_metadata") from exc
    packages = []
    for package_name in names:
        try:
            distribution = metadata.distribution(package_name)
        except metadata.PackageNotFoundError:
            packages.append({"name": package_name, "installed": False, "version": None})
            continue
        packages.append({"name": package_name, "installed": True,
                         "version": _version(distribution.version)})
    return {
        "project": {"name": name, "version": version, "file": "pyproject.toml",
                    "sha256": hashlib.sha256(raw).hexdigest()},
        "dependencies": {"scope": "declared_direct_distributions_only",
                         "markers_evaluated": False, "selected_extras": selected,
                         "packages": packages},
    }


def _model_path(value: object) -> str:
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise ProvenanceError("invalid_model_relative_path")
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or value != path.as_posix()
            or any(part in {".", ".."} for part in path.parts)):
        raise ProvenanceError("invalid_model_relative_path")
    if (len(path.parts) > 3 or any(not _MODEL_DIR.fullmatch(part) for part in path.parts[:-1])
            or not (path.name in _MODEL_NAMES or _MODEL_SHARD.fullmatch(path.name))):
        raise ProvenanceError("model_file_not_allowlisted")
    return path.as_posix()


def _model_limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_MODEL_BYTES:
        raise ProvenanceError("invalid_model_byte_limit")
    return value


def _model_files(files: object, max_bytes: int) -> list[dict[str, Any]]:
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_MODEL_FILES:
        raise ProvenanceError("invalid_model_file_count")
    validated = []
    seen = set()
    total = 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size_bytes"}:
            raise ProvenanceError("invalid_model_file_entry")
        relative = _model_path(entry["path"])
        digest, size = entry["sha256"], entry["size_bytes"]
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ProvenanceError("invalid_model_sha256")
        if type(size) is not int or size < 0:
            raise ProvenanceError("invalid_model_size")
        total += size
        # Case-fold prevents aliases on case-insensitive Windows filesystems.
        if relative.casefold() in seen:
            raise ProvenanceError("duplicate_model_file")
        if total > max_bytes:
            raise ProvenanceError("model_byte_limit_exceeded")
        seen.add(relative.casefold())
        validated.append({"path": relative, "sha256": digest, "size_bytes": size})
    return sorted(validated, key=lambda item: item["path"])


def model_from_manifest(manifest: Path, max_bytes: int) -> dict[str, Any]:
    """Validate declared hashes only; never label a manifest as an observed model."""
    _model_limit(max_bytes)
    raw = _read_file(manifest, MAX_METADATA_BYTES)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ProvenanceError("invalid_model_manifest_json") from exc
    if (not isinstance(data, dict) or set(data) != {"schema", "version", "files"}
            or data["schema"] != MANIFEST_SCHEMA or type(data["version"]) is not int
            or data["version"] != 1):
        raise ProvenanceError("invalid_model_manifest_schema")
    files = _model_files(data["files"], max_bytes)
    return {"mode": "manifest", "verification": "declared_not_verified", "files": files,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "selection_sha256": hashlib.sha256(canonical_json(files)).hexdigest()}


def model_from_root(root: Path, files: Sequence[str], max_bytes: int) -> dict[str, Any]:
    """Hash only explicitly named, allowlisted model files with a total read budget."""
    _model_limit(max_bytes)
    if not 1 <= len(files) <= MAX_MODEL_FILES:
        raise ProvenanceError("explicit_model_files_required")
    root = root.absolute()
    _no_links(root)
    if not root.is_dir():
        raise ProvenanceError("model_root_not_directory")
    paths = [_model_path(item) for item in files]
    if len({item.casefold() for item in paths}) != len(paths):
        raise ProvenanceError("duplicate_model_file")
    entries = []
    remaining = max_bytes
    for relative in sorted(paths):
        path = root.joinpath(*PurePosixPath(relative).parts)
        before = _regular_stat(path)
        if before.st_size > remaining:
            raise ProvenanceError("model_byte_limit_exceeded")
        digest = hashlib.sha256()
        size = 0
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            if not _same_file(before, os.fstat(stream.fileno())):
                raise ProvenanceError("input_changed_during_read")
            while block := stream.read(min(1024 * 1024, remaining - size + 1)):
                size += len(block)
                if size > remaining:
                    raise ProvenanceError("model_byte_limit_exceeded")
                digest.update(block)
            after = os.fstat(stream.fileno())
        if not _same_file(before, after) or not _same_file(before, _regular_stat(path)):
            raise ProvenanceError("input_changed_during_read")
        remaining -= size
        entries.append({"path": relative, "size_bytes": size, "sha256": digest.hexdigest()})
    return {"mode": "explicit_files", "verification": "selected_bytes_hashed_not_full_model",
            "files": entries, "selection_sha256": hashlib.sha256(
                canonical_json(entries)).hexdigest()}


def build_report(project_root: Path, *, extras: Sequence[str] | None = None,
                 db_image_digest: str | None = None, model_manifest: Path | None = None,
                 model_root: Path | None = None, model_files: Sequence[str] = (),
                 model_max_bytes: int = DEFAULT_MODEL_MAX_BYTES,
                 timestamp: bool = False) -> dict[str, Any]:
    """Build a path-free report; default operation performs no file writes."""
    if (db_image_digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}",
                                                       db_image_digest)):
        raise ProvenanceError("db_image_digest_requires_sha256_not_tag")
    _model_limit(model_max_bytes)
    if model_manifest is not None and (model_root is not None or model_files):
        raise ProvenanceError("model_inputs_mutually_exclusive")
    if model_files and model_root is None:
        raise ProvenanceError("model_root_required")
    models: dict[str, Any] = {"mode": "not_requested", "verification": "not_observed",
                              "files": []}
    if model_manifest is not None:
        models = model_from_manifest(model_manifest, model_max_bytes)
    elif model_root is not None:
        models = model_from_root(model_root, model_files, model_max_bytes)
    inventory = project_inventory(project_root, extras)
    content = {
        **inventory,
        "runtime": {"python_version": platform.python_version(),
                    "python_implementation": platform.python_implementation(),
                    "os": platform.system(), "os_release": platform.release(),
                    "architecture": platform.machine()},
        "database": {"image_digest": db_image_digest,
                     "verification": "operator_declared_not_runtime_verified"
                     if db_image_digest else "not_observed"},
        "model": models,
        "reproducibility": {"classification": "provenance_not_lock",
                            "linux_cpu_lock": "not_built_or_validated",
                            "transitive_dependencies_locked": False},
    }
    report = {"schema": SCHEMA, "version": SCHEMA_VERSION, "content": content,
              "content_sha256": hashlib.sha256(canonical_json(content)).hexdigest()}
    if timestamp:
        report["observed_at_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def write_report(report: dict[str, Any], output: Path, project_root: Path) -> None:
    """Exclusively create a JSON report inside the project; never replace a file."""
    project_root = project_root.absolute()
    output = output if output.is_absolute() else project_root / output
    output = output.absolute()
    _no_links(project_root)
    _no_links(output)
    try:
        output.resolve().relative_to(project_root.resolve(strict=True))
    except ValueError as exc:
        raise ProvenanceError("output_must_stay_inside_project") from exc
    if output.suffix.lower() != ".json" or not output.parent.is_dir():
        raise ProvenanceError("output_requires_existing_directory_and_json_suffix")
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(output, flags, 0o600)
    except FileExistsError as exc:
        raise ProvenanceError("output_already_exists") from exc
    identity = os.fstat(fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Remove only the inode created by this call, never a concurrent replacement.
        try:
            current = output.lstat()
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                output.unlink()
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    """Construct the explicit, offline-only CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extra", action="append", default=None,
                        help="Declared extra to inventory; repeatable, default: web if present")
    parser.add_argument("--db-image-digest", help="Operator-supplied sha256:<64 lowercase hex>")
    model = parser.add_mutually_exclusive_group()
    model.add_argument("--model-manifest", type=Path, help="Read declared model hash manifest")
    model.add_argument("--model-root", type=Path, help="Explicit root; no discovery or recursion")
    parser.add_argument("--model-file", action="append", default=[],
                        help="Allowlisted relative model file; repeat for every selected file")
    parser.add_argument("--model-max-bytes", type=int, default=DEFAULT_MODEL_MAX_BYTES,
                        help="Total selected bytes, default 64 MiB; hard maximum 16 GiB")
    parser.add_argument("--timestamp", action="store_true", help="Separate observation time")
    parser.add_argument("--output", type=Path,
                        help="New .json in an existing project directory; default: stdout only")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print native JSON or exclusively write it, returning sanitized error codes."""
    args = build_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    try:
        report = build_report(project_root, extras=args.extra,
                              db_image_digest=args.db_image_digest,
                              model_manifest=args.model_manifest, model_root=args.model_root,
                              model_files=args.model_file, model_max_bytes=args.model_max_bytes,
                              timestamp=args.timestamp)
        if args.output is not None:
            write_report(report, args.output, project_root)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except ProvenanceError as exc:
        print(f"provenance_error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"provenance_io_error: errno={exc.errno}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
