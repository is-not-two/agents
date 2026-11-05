"""Rebuild the current CSS by concatenating canonical, order-preserving segments."""
from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
from pathlib import Path

PARTS = ("00-header-and-product.css", "10-base.css", "20-demo.css", "30-tree.css",
         "40-automation-and-later.css")
DEFAULT_ROOT = (Path(__file__).resolve().parent.parent / "src" / "rag_tech_retriever"
                / "api" / "static" / "shilie")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--css-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--check", action="store_true", help="compare only; do not write")
    args = parser.parse_args()
    root = args.css_root.resolve()
    try:
        data = b"".join((root / "css_sources" / name).read_bytes() for name in PARTS)
        destination = root / "app.css"
        if args.check:
            if not destination.is_file() or destination.read_bytes() != data:
                print("FAIL: app.css differs from ordered CSS sources")
                return 1
            print(f"OK: app.css matches {len(PARTS)} ordered sources; sha256={hashlib.sha256(data).hexdigest()}")
            return 0
        descriptor, name = tempfile.mkstemp(prefix=".app-css-", dir=root)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, destination)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        print(f"Wrote app.css from {len(PARTS)} ordered sources; sha256={hashlib.sha256(data).hexdigest()}")
        return 0
    except OSError as exc:
        print(f"FAIL: CSS source or output unavailable: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
