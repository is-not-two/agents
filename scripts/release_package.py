"""Package only the exact source accepted by a full gate; never deploy a server."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from rag_tech_retriever.common.release_manifest import source_manifest


def _write_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    """Fix metadata as well as contents; host clock and umask are not release inputs."""
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _remove_own_publication(path: Path, staged: Path) -> None:
    """Compensate only our regular-file inode; never follow a replacement symlink."""
    try:
        current, original = path.lstat(), staged.lstat()
    except FileNotFoundError:
        return
    if (stat.S_ISREG(current.st_mode)
            and (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino)):
        path.unlink(missing_ok=True)


def build(root: Path, report_path: Path, output: Path) -> dict:
    """Stage deterministic source-only ZIP/SHA and publish each without overwriting.

    Hard-link support and a trusted output directory are required. Compensation is
    not a two-path atomic transaction: a process crash can leave an orphaned ZIP.
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = source_manifest(root)
    if (report.get("schema") != 1 or report.get("level") != "full"
            or report.get("passed") is not True or report.get("source_manifest") != manifest):
        raise ValueError("发布门禁未全量通过，或报告与当前源不一致")
    checksum = output.with_suffix(output.suffix + ".sha256")
    if os.path.lexists(output) or os.path.lexists(checksum):
        raise ValueError("发布包或校验文件已存在，拒绝覆盖")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged_zip = staged_sha = None
    published: list[tuple[Path, Path]] = []
    committed = False
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".release-zip-",
                                         suffix=".tmp", delete=False) as stream:
            staged_zip = Path(stream.name)
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, digest in sorted(manifest.items()):
                    data = (root / name).read_bytes()
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError("打包期间发布源发生变化")
                    _write_entry(archive, name, data)
                _write_entry(archive, "RELEASE-MANIFEST.json",
                             json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        result = {"sha256": hashlib.sha256(staged_zip.read_bytes()).hexdigest(),
                  "files": len(manifest)}
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".release-sha-",
                                         suffix=".tmp", delete=False) as stream:
            staged_sha = Path(stream.name)
            stream.write((result["sha256"] + "  " + output.name + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if source_manifest(root) != manifest:
            raise ValueError("打包期间发布源发生变化")
        # Unlike rename/replace, link is atomic and refuses even a racing target.
        for staged, target in ((staged_zip, output), (staged_sha, checksum)):
            os.link(staged, target)
            published.append((target, staged))
        if source_manifest(root) != manifest:
            raise ValueError("打包期间发布源发生变化")
        committed = True
        return result
    finally:
        try:
            if not committed:
                for target, staged in reversed(published):
                    _remove_own_publication(target, staged)
        finally:
            for staged in (staged_sha, staged_zip):
                if staged is not None:
                    staged.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(PROJECT, args.report, args.output)))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile):
        print("RELEASE_BLOCKED: 门禁、源指纹或发布路径无效", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
