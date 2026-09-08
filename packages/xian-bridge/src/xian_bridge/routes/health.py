"""
GET /health — Service status endpoint.

Returns version info and whether OCR / document backends are available.
MASHA probes this at startup (300 ms timeout) to decide which features to show.
"""

from fastapi import APIRouter

from .. import __version__
from .documents import IMPLEMENTED as _documents_available
from .ocr import IMPLEMENTED as _ocr_available

router = APIRouter()


@router.get("/health")
async def health():
    # Read straight from the route modules: advertising a capability whose
    # every endpoint returns 501 would light up UI that cannot work.
    return {
        "version": __version__,
        "ocr": _ocr_available,
        "documents": _documents_available,
    }
