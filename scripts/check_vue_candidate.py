"""Build a Vue-only candidate wheel in temporary space and exercise its FastAPI entry."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from check_wheel_assets import verify_wheel

PROJECT = Path(__file__).resolve().parents[1]
STATIC = Path("rag_tech_retriever/api/static")
BASE = "/static/vue/"
RETIRED_ENTRYPOINTS = (
    "static-version.txt", "check_static_version.py", "check_static_assets.py", "verify-ui.mjs",
    "serve-mock.mjs", "web_regression.py",
)
SMOKE = """
from pathlib import Path
import json
import sys
from fastapi.testclient import TestClient
from rag_tech_retriever.api import main

assert Path(main.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
# Do not enter the lifespan: static routing needs no database.
client = TestClient(main.app)
home = client.get("/")
assert home.status_code == 200
assert home.content == Path(sys.argv[2]).read_bytes()
for url in json.loads(sys.argv[3]):
    response = client.get(url)
    assert response.status_code == 200, url
assert client.get("/legacy").status_code == 404
assert client.get("/static/shilie/app.js").status_code == 404
assert client.get("/static/index.html").status_code == 404
assert client.get("/api/session").status_code == 200
"""


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    """Fail with diagnostics, and never install or retrieve dependencies."""
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=180, check=False)
    if result.returncode:
        raise RuntimeError((result.stdout + "\n" + result.stderr)[-4000:])


def check_source_layout(project: Path) -> None:
    """Do not silently omit retired frontend files when preparing the wheel."""
    static = project / "src" / STATIC
    retired = [path.relative_to(project).as_posix() for path in static.glob("*") if path.name != "vue"]
    retired += ["scripts/" + name for name in RETIRED_ENTRYPOINTS if (project / "scripts" / name).exists()]
    if retired:
        raise RuntimeError("旧前端残留：" + ", ".join(sorted(retired)))


def check(emit_assets: Path | None = None) -> int:
    """Validate the wheel bytes and HTTP results; return the number of served assets."""
    check_source_layout(PROJECT)
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("npm is required; dependencies must already be available locally")
    with tempfile.TemporaryDirectory(prefix="shilie-vue-candidate-") as name:
        root = Path(name)
        stage = root / "source"
        stage.mkdir()
        for filename in ("pyproject.toml", "README.md"):
            shutil.copy2(PROJECT / filename, stage / filename)

        def omit(path: str, entries: list[str]) -> list[str]:
            here = Path(path)
            return [entry for entry in entries if entry == "__pycache__" or entry.endswith(".pyc")
                    or (here.name == "api" and entry == "static")]

        shutil.copytree(PROJECT / "src", stage / "src", ignore=omit)
        vue = stage / "src" / STATIC / "vue"
        run([npm, "run", "build", "--", "--base", BASE, "--outDir", str(vue)], PROJECT / "shilie")
        run([sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
             "--no-build-isolation", "--no-cache-dir", str(stage), "-w", str(root / "dist")], root)
        wheels = list((root / "dist").glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("Expected exactly one candidate wheel")
        missing, changed = verify_wheel(stage, wheels[0])
        if missing or changed:
            raise RuntimeError(f"Candidate static assets missing={missing}, changed={changed}")
        installed = root / "installed"
        prefix = STATIC.as_posix() + "/"
        with zipfile.ZipFile(wheels[0]) as archive:
            names = [item for item in archive.namelist() if item.startswith(prefix) and not item.endswith("/")]
            if not names or any(not item.startswith(prefix + "vue/") for item in names):
                raise RuntimeError("Candidate contains old frontend assets or no Vue assets")
            archive.extractall(installed)
        index = installed / STATIC / "vue" / "index.html"
        html = index.read_text(encoding="utf-8")
        if not re.search(r'<script[^>]+src="/static/vue/assets/[^"]+\.js"', html):
            raise RuntimeError("Candidate home does not load a packaged Vue entry")
        paths = ["/" + item.removeprefix("rag_tech_retriever/api/") for item in names]
        for css in (installed / STATIC / "vue" / "assets").glob("*.css"):
            for reference in re.findall(r"url\(([^)]+)\)", css.read_text(encoding="utf-8")):
                url = reference.strip("'\"")
                if url.startswith("/") and url not in paths:
                    raise RuntimeError(f"CSS refers to missing packaged asset: {url}")
        fixture = root / "runtime"
        fixture.mkdir()
        shutil.copytree(PROJECT / "config", fixture / "config",
                        ignore=shutil.ignore_patterns(".env*", "*.local*", "*.key", "*.pem"))
        # Keep process necessities only; no inherited model, database or account credentials.
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}}
        env.update(RAG_PROJECT_ROOT=str(fixture), PYTHONPATH=str(installed), PYTHONUTF8="1",
                   PYTHONDONTWRITEBYTECODE="1", WORKSPACE_PROFILE="local")
        run([sys.executable, "-c", SMOKE, str(installed), str(index), json.dumps(paths)], root, env)
        if emit_assets is not None:
            # Copy only the byte-for-byte assets that were served from the verified wheel.
            shutil.copytree(index.parent, emit_assets)
        return len(paths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-assets", type=Path)
    args = parser.parse_args()
    try:
        print(f"VUE_CANDIDATE_PASSED packaged_http_assets={check(args.emit_assets)} legacy=404 database=not_exercised")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        print(f"VUE_CANDIDATE_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
