"""
FastAPI application for the Xian bridge.

This service can OCR arbitrary images, and it listens on loopback where every
page in the user's browser can reach it. Three guards, because CORS alone is
not one:

* **Host allowlist** — a DNS name that resolves to 127.0.0.1 (a rebinding
  attack) carries an off-list ``Host`` header and is rejected before routing.
* **Origin allowlist** — CORS only stops a page *reading* the response; a
  simple ``POST`` (``Content-Type: text/plain``) is sent with no preflight and
  its side effects still happen. Browsers always attach ``Origin`` to a
  cross-origin POST, so rejecting off-list origins outright is what actually
  closes that door.
* **Loopback bind** — see ``__main__.py``.

Still open by design: any *local* process can call the bridge, exactly as it
can call Lemonade itself. Closing that needs a shared secret the extension can
read, which is a change on both sides of the wire.
"""

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .routes.health import router as health_router
from .routes.ocr import router as ocr_router
from .routes.documents import router as documents_router
from .routes.cache import router as cache_router
from .routes.glossary import router as glossary_router


# Extension origins that may call the bridge. The Chrome ID is only known once
# the extension is packed, so it comes from the environment rather than a
# placeholder that would reject the real extension on day one:
#
#     MASHA_EXTENSION_ORIGINS=chrome-extension://<32-char-id>[,…]
DEFAULT_EXTENSION_ORIGINS: set[str] = {
    # Firefox extension ID
    "moz-extension://masha@pendragon.systems",
    # WXT dev server (localhost)
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

# Host headers accepted. Anything else is a rebinding attempt or a misroute.
ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "[::1]", "::1"]


def extension_origins() -> set[str]:
    """Allowlisted origins: the built-in set plus anything the environment adds."""
    configured = os.environ.get("MASHA_EXTENSION_ORIGINS", "")
    extra = {origin.strip() for origin in configured.split(",") if origin.strip()}
    return DEFAULT_EXTENSION_ORIGINS | extra


def create_app() -> FastAPI:
    app = FastAPI(title="Xian Bridge", version="1.0.0")
    origins = extension_origins()

    @app.middleware("http")
    async def reject_foreign_origins(request: Request, call_next):
        # No Origin at all is a non-browser caller (curl, a local tool); a
        # browser page always sends one cross-origin, so an off-list value is
        # a page trying its luck and never the extension.
        origin = request.headers.get("origin")
        if origin is not None and origin not in origins:
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        return await call_next(request)

    # Host header — blocks DNS rebinding onto the loopback port
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    # CORS — only extension origins may read responses
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    # Mount routes
    app.include_router(health_router)
    app.include_router(ocr_router)
    app.include_router(documents_router)
    app.include_router(cache_router)
    app.include_router(glossary_router)

    return app
