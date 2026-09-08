"""
OCR routes — text extraction from images and comic balloon grouping.

POST /ocr        — OCR an image → blocks with quads
POST /ocr/render — Inpaint translated blocks onto an image (overlay mode)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

router = APIRouter(prefix="/ocr")

# True once the PaddleOCR engine is wired in place of the 501 stubs below.
# /health reports this verbatim, so the two can never drift apart.
IMPLEMENTED = False


class OcrRequest(BaseModel):
    image: str  # base64-encoded image bytes
    source_lang: str = "Auto"
    mode: Literal["text", "comic"] = "text"


class Quad(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    x3: float
    y3: float
    x4: float
    y4: float


class Block(BaseModel):
    quad: Quad
    text: str
    confidence: float


class OcrResponse(BaseModel):
    blocks: list[Block]
    size: dict[str, int]  # {width, height}


@router.post("", response_model=OcrResponse)
async def ocr(request: OcrRequest):
    """
    Run PP-OCRv5 detector + recognizer on the provided image.

    * ``mode="text"`` — standard reading-order blocks.
    * ``mode="comic"`` — speech-bubble grouping, panel ordering.
    """
    # Stub — real implementation will call xian.ocr.PaddleOcrEngine
    raise HTTPException(status_code=501, detail="OCR not yet implemented")


class OcrRenderRequest(BaseModel):
    image: str  # base64-encoded image bytes
    blocks: list[dict]  # [{quad: …, translated: …}]


class OcrRenderResponse(BaseModel):
    image: str  # base64-encoded inpainted result


@router.post("/render", response_model=OcrRenderResponse)
async def ocr_render(request: OcrRenderRequest):
    """
    Render translated text blocks back onto the image (inpaint overlay).
    """
    # Stub — real implementation will use the xian inpaint pipeline
    raise HTTPException(status_code=501, detail="OCR render not yet implemented")
