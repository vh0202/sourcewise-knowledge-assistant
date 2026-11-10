"""FastAPI application factory.

The API lives under ``/api``; everything else is the pre-built React app from
``frontend/dist``, so the whole product is served from one port with no Node process.

Run with ``python -m sourcewise serve`` (or ``uvicorn sourcewise.main:create_app --factory``).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__
from .api import api_router
from .config import Settings, get_settings
from .container import Container, build_container

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # Everything is same-origin: no CDNs, no inline scripts. Inline styles are allowed
    # because the UI sets a few dynamic widths through the style attribute.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}

_FRONTEND_MISSING = """<!doctype html><meta charset="utf-8"><title>SourceWise</title>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; line-height: 1.5">
<h1>SourceWise API is running</h1>
<p>The web interface has not been built. From the <code>frontend</code> folder run
<code>npm install</code> and <code>npm run build</code>, then reload this page.</p></body>"""


class SecurityHeadersMiddleware:
    """Adds baseline security headers to every HTTP response (pure ASGI, so streaming is untouched)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        if not index.is_file():
            return HTMLResponse(_FRONTEND_MISSING)
        if path:
            candidate = (dist / path).resolve()
            if candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
        # Any other path is a client-side route: serve the app shell and let the router decide.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(settings: Settings | None = None, *, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        container.close()

    app = FastAPI(
        title="SourceWise API",
        version=__version__,
        description="Knowledge assistant with cited answers. Sample project; all data is synthetic.",
        # The interactive docs pages load their scripts from a CDN, which this project
        # deliberately avoids; the OpenAPI schema itself is still published.
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.container = container
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(api_router)
    _mount_frontend(app, settings.frontend_dist)
    return app
