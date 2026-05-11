from __future__ import annotations

import base64
import time
from typing import Any, Literal

import structlog
import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import logging as mcpfs_logging
from .config import Settings, load_settings
from .gcs import GcsBackend
from .identity import Caller, parse_caller
from .paths import normalize, normalize_prefix

log = mcpfs_logging.get_logger("mcpfs")


def _build_mcp(backend: GcsBackend) -> FastMCP:
    mcp = FastMCP(
        name="mcpfs",
        instructions=(
            "Filesystem semantics over a Google Cloud Storage bucket. Paths are "
            "forward-slash separated object names. Listings can scope to a prefix and "
            "may be recursive. Reads and writes are bounded by a server-side size "
            "limit; binary payloads must be base64-encoded. Writes return a generation "
            "callers can pass back as if_generation_match for optimistic concurrency."
        ),
    )

    @mcp.tool(
        name="fs_list",
        description=(
            "List entries under a prefix. Returns objects (kind='file') and, when "
            "recursive=false, child directories (kind='prefix'). Empty prefix lists the root."
        ),
    )
    def fs_list(prefix: str = "", recursive: bool = False) -> dict[str, Any]:
        norm = normalize_prefix(prefix)
        entries = list(backend.list(norm, recursive=recursive))
        log.info("fs.list", prefix=norm, recursive=recursive, count=len(entries))
        return {
            "prefix": norm,
            "recursive": recursive,
            "entries": [
                {"name": e.name, "kind": e.kind, "size": e.size, "updated": e.updated}
                for e in entries
            ],
        }

    @mcp.tool(
        name="fs_stat",
        description="Return metadata for a single object without downloading it.",
    )
    def fs_stat(path: str) -> dict[str, Any]:
        name = normalize(path)
        stat = backend.stat(name)
        log.info("fs.stat", path=name, generation=stat.generation, size=stat.size)
        return {
            "name": stat.name,
            "size": stat.size,
            "updated": stat.updated,
            "content_type": stat.content_type,
            "md5_hash": stat.md5_hash,
            "generation": stat.generation,
        }

    @mcp.tool(
        name="fs_read",
        description=(
            "Read an object. Returns 'content' as utf-8 text when valid, else base64 "
            "(see 'encoding'). Subject to the server's max_object_bytes limit."
        ),
    )
    def fs_read(path: str) -> dict[str, Any]:
        name = normalize(path)
        data, stat = backend.read(name)
        try:
            text = data.decode("utf-8")
            encoding: Literal["utf-8", "base64"] = "utf-8"
            content = text
        except UnicodeDecodeError:
            encoding = "base64"
            content = base64.b64encode(data).decode("ascii")
        log.info(
            "fs.read", path=name, size=stat.size, encoding=encoding, generation=stat.generation
        )
        return {
            "name": stat.name,
            "size": stat.size,
            "encoding": encoding,
            "content": content,
            "content_type": stat.content_type,
            "generation": stat.generation,
            "md5_hash": stat.md5_hash,
        }

    @mcp.tool(
        name="fs_write",
        description=(
            "Write an object. encoding is 'utf-8' (default) or 'base64'. Pass "
            "if_generation_match=0 to require creation only; pass an existing "
            "generation to require an unchanged predecessor."
        ),
    )
    def fs_write(
        path: str,
        content: str,
        encoding: Literal["utf-8", "base64"] = "utf-8",
        content_type: str | None = None,
        if_generation_match: int | None = None,
    ) -> dict[str, Any]:
        name = normalize(path)
        if encoding == "utf-8":
            data = content.encode("utf-8")
        else:
            try:
                data = base64.b64decode(content, validate=True)
            except ValueError as e:
                raise ValueError(f"invalid base64 content: {e}") from e
        stat = backend.write(
            name,
            data,
            content_type=content_type,
            if_generation_match=if_generation_match,
        )
        log.info(
            "fs.write",
            path=name,
            size=stat.size,
            generation=stat.generation,
            if_generation_match=if_generation_match,
        )
        return {
            "name": stat.name,
            "size": stat.size,
            "generation": stat.generation,
            "updated": stat.updated,
        }

    @mcp.tool(
        name="fs_delete",
        description=(
            "Delete an object. Pass if_generation_match to delete only when the live "
            "generation matches. The bucket has object versioning enabled, so deletions "
            "are recoverable until the lifecycle policy expires noncurrent versions."
        ),
    )
    def fs_delete(path: str, if_generation_match: int | None = None) -> dict[str, Any]:
        name = normalize(path)
        backend.delete(name, if_generation_match=if_generation_match)
        log.info("fs.delete", path=name, if_generation_match=if_generation_match)
        return {"name": name, "deleted": True}

    return mcp


class IdentityMiddleware:
    """Bind caller identity into log context; reject calls without identity when required."""

    def __init__(self, app: ASGIApp, require_identity: bool) -> None:
        self._app = app
        self._require = require_identity

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        auth_header: str | None = None
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth_header = value.decode("latin-1")
                break

        caller: Caller | None = parse_caller(auth_header)
        path = scope.get("path", "")
        if self._require and caller is None and path != "/healthz":
            response = JSONResponse(
                {"error": "missing or unparseable caller identity"}, status_code=401
            )
            await response(scope, receive, send)
            return

        tokens = structlog.contextvars.bind_contextvars(
            caller_sub=caller.sub if caller else None,
            caller_email=caller.email if caller else None,
            request_path=path,
        )
        start = time.monotonic()
        status_holder = {"status": 0}

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            log.info(
                "http.request",
                status=status_holder["status"],
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            structlog.contextvars.reset_contextvars(**tokens)


def _healthz(_: Request) -> Response:
    return JSONResponse({"status": "ok"})


def build_app(settings: Settings | None = None) -> Starlette:
    settings = settings or load_settings()
    mcpfs_logging.configure(settings.log_level)
    backend = GcsBackend(
        bucket_name=settings.bucket,
        max_object_bytes=settings.max_object_bytes,
        list_page_size=settings.list_page_size,
    )
    mcp = _build_mcp(backend)
    mcp_app = mcp.streamable_http_app()

    app = Starlette(
        routes=[
            Route("/healthz", _healthz, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
    )
    app.add_middleware(IdentityMiddleware, require_identity=settings.require_identity_header)
    log.info(
        "mcpfs.startup",
        bucket=settings.bucket,
        max_object_bytes=settings.max_object_bytes,
        require_identity=settings.require_identity_header,
    )
    return app


def main() -> None:
    settings = load_settings()
    app = build_app(settings)
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 - container ingress is bounded by Cloud Run
        port=settings.port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
