"""
GET /health — Service status endpoint.

Returns version info and whether OCR / document backends are available.
MASHA probes this at startup (300 ms timeout) to decide which features to show.
"""

from fastapi import APIRouter
from .. import __version__

router = APIRouter()

# Placeholder: real availability checks will be wired once the backends are
# imported. For now both report as available (the default state when MAGE is
# running with the full stack).
_ocr_available = True
_documents_available = True


@router.get("/health")
async def health():
    return {
        "version": __version__,
        "ocr": _ocr_available,
        "documents": _documents_available,
    }
