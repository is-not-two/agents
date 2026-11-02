"""Pinned native runner: actual production app, verify-only preflight and loopback identity."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_DLL_DIRECTORIES = []


def application(args):
    """Import only the selected staged source; never install dependencies or migrate schema."""
    release = args.release_root.resolve(strict=True)
    shared = args.shared_root.resolve(strict=True)
    # ConfigLoader.resolve, .env, private vault metadata and all file-backed
    # services must agree on one persistent root, not inherit an old checkout.
    # Active config is operator-prepared in shared/config; never copied here.
    os.environ["RAG_PROJECT_ROOT"] = str(shared)
    os.environ["PROJECT_ROOT"] = str(shared)
    os.environ["WORKSPACE_PROFILE"] = "production"
    os.environ["WORKSPACE_SCHEMA_MODE"] = "verify"
    if args.site_packages:
        sites = Path(args.site_packages).resolve(strict=True)
        sys.path.insert(0, str(sites))
        if os.name == "nt":
            # pywin32's documented layout is normally added by an executable
            # .pth; isolated direct-Python mode adds only these fixed paths.
            for relative in ("win32", "win32/lib", "pythonwin"):
                directory = sites / relative
                if directory.is_dir() and directory.resolve().is_relative_to(sites):
                    sys.path.insert(0, str(directory))
            dlls = sites / "pywin32_system32"
            if dlls.is_dir() and dlls.resolve().is_relative_to(sites):
                _DLL_DIRECTORIES.append(os.add_dll_directory(str(dlls)))
    sys.path.insert(0, str(release / "src"))
    from rag_tech_retriever.api.main import create_app
    app = create_app(root=shared)
    identity = {"release_id": args.release_id, "source_sha256": args.source_sha256,
                "nonce": args.nonce, "pid": os.getpid()}

    async def wrapped(scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/health/release":
            # A middleware-free identity, not readiness: actual /health/ready still probes DB.
            body = json.dumps(identity, sort_keys=True).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})
        else:
            await app(scope, receive, send)
    return app, wrapped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preflight", "serve"])
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--shared-root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--site-packages", default="")
    args = parser.parse_args()
    phase = "APPLICATION"
    try:
        app, wrapped = application(args)
        if args.action == "preflight":
            phase = "LIFESPAN"
            async def preflight():
                async with app.router.lifespan_context(app):
                    pass
            asyncio.run(preflight())
        else:
            phase = "SERVE"
            import uvicorn
            uvicorn.run(wrapped, host="127.0.0.1", port=args.port, access_log=False, log_level="critical")
        return 0
    except Exception as exc:  # noqa: BLE001 - process boundary must redact arbitrary application startup errors
        # Do not echo library errors: DB DSNs, tokens and provider inputs may be sensitive.
        if isinstance(exc, ImportError):
            phase = "DEPENDENCY"
        print("NATIVE_APP_NOT_READY_" + phase, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
