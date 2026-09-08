"""
FastAPI application for the Xian bridge.

Routes are CORS-constrained to extension origins only — this service can OCR
arbitrary images and must not be reachable from any web page.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes.health import router as health_router
from .routes.ocr import router as ocr_router
from .routes.documents import router as documents_router
from .routes.cache import router as cache_router
from .routes.glossary import router as glossary_router


# Extension origins that may call the bridge. In production these are the
# Chrome/Firefox extension IDs — in dev the WXT dev server origin.
EXTENSION_ORIGINS: set[str] = {
    # Chrome extension ID (production)
    "chrome-extension://masha-translate-extension-id",
    # Firefox extension ID
    "moz-extension://masha@pendragon.systems",
    # WXT dev server (localhost)
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


def create_app() -> FastAPI:
    app = FastAPI(title="Xian Bridge", version="1.0.0")

    # CORS — only extension origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(EXTENSION_ORIGINS),
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
