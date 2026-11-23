"""Run the Vue browser contract suite on a temporary loopback demo and production build."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    frontend = PROJECT / "shilie"
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        raise RuntimeError("Node and locally installed Vue dependencies are required")
    with tempfile.TemporaryDirectory(prefix="shilie-vue-browser-") as folder:
        dist = Path(folder) / "dist"
        subprocess.run([npm, "run", "build", "--", "--outDir", str(dist)], cwd=frontend,
                       check=True, timeout=180)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen([node, "node_modules/vite/bin/vite.js", "--mode", "demo",
                                 "--host", "127.0.0.1", "--port", str(port), "--strictPort"], cwd=frontend)
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError("Vue demo failed to start")
                try:
                    with urllib.request.urlopen(base, timeout=1):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("Vue demo startup timed out")
            subprocess.run([node, "scripts/verify-demo.mjs"], cwd=frontend, check=True, timeout=150,
                           env={**os.environ, "SHILIE_DEMO_URL": base, "SHILIE_BUILD_DIR": str(dist)})
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == "__main__":
    main()
