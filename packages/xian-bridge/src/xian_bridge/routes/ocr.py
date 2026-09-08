"""
OCR routes — text extraction from images and comic balloon grouping.

POST /ocr        — OCR an image → blocks with quads
POST /ocr/render — Inpaint translated blocks onto an image (overlay mode)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional
import asyncio
import base64
import importlib.util
import io
from PIL import Image

router = APIRouter(prefix="/ocr")


def _engine_installed() -> bool:
    """Whether xian-vl's PP-OCRv5 reader can actually be built here.

    ``xian-vl[ocr]`` is an optional extra; without ONNX Runtime the engine
    imports but cannot run.
    """
    try:
        return all(
            importlib.util.find_spec(name) is not None
            for name in ("onnxruntime", "xian.ocr.engine")
        )
    except (ImportError, ValueError):
        return False


# True when the PaddleOCR engine is present. /health reports this verbatim, so
# the two can never drift apart — and MASHA only offers image translation when
# there is an engine behind it.
IMPLEMENTED = _engine_installed()

# One engine per source language; building an ONNX session is expensive.
_engines: dict[str, object] = {}


def _engine_for(source_lang: str):
    key = source_lang or "Auto"
    if key not in _engines:
        from xian.ocr import PaddleOcrEngine

        _engines[key] = PaddleOcrEngine(source_language=None if key == "Auto" else key)
    return _engines[key]


#: Languages written without spaces between words, where joining detections on
#: one baseline with a space is a visible error.
_UNSPACED = {"Chinese", "Japanese", "Korean", "Thai"}


def _decode_image(encoded: str) -> bytes:
    """Bytes from either a bare base64 payload or a full ``data:`` URL."""
    payload = encoded.split(",", 1)[1] if "," in encoded else encoded
    return base64.b64decode(payload, validate=True)


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
    if not IMPLEMENTED:
        raise HTTPException(
            status_code=501,
            detail="OCR engine not installed — install the xian-vl[ocr] extra",
        )

    # Decode base64 image
    try:
        image_bytes = _decode_image(request.image)
    except (ValueError, base64.binascii.Error):
        raise HTTPException(status_code=400, detail="Invalid base64 image")

    # Load image with PIL to get dimensions
    try:
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = pil_image.size
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    import numpy as np

    from xian.ocr.grouping import group_lines

    # The engine reads BGR, and its `read` is synchronous by design — it
    # expects a worker thread, never the loop every other request shares.
    bgr = np.asarray(pil_image)[:, :, ::-1]
    engine = _engine_for(request.source_lang)
    try:
        lines = await asyncio.to_thread(engine.read, bgr)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"OCR failed: {e}")

    # Comic mode reads right-to-left: panel ordering is grouping's business.
    grouped = group_lines(
        lines,
        space_delimited=request.source_lang not in _UNSPACED,
        rtl=request.mode == "comic",
    )

    blocks: list[Block] = []
    for block in grouped:
        x1, y1, x2, y2 = block.box
        blocks.append(Block(
            quad=Quad(x1=x1, y1=y1, x2=x2, y2=y1, x3=x2, y3=y2, x4=x1, y4=y2),
            text=block.text,
            confidence=block.confidence,
        ))

    return OcrResponse(blocks=blocks, size={"width": width, "height": height})


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
    # Decode base64 image
    try:
        image_bytes = _decode_image(request.image)
    except (ValueError, base64.binascii.Error):
        raise HTTPException(status_code=400, detail="Invalid base64 image")

    try:
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    # Draw translated text onto the image
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(pil_image)

    for block_data in request.blocks:
        quad = block_data.get("quad", {})
        translated = block_data.get("translated", "")

        x1 = quad.get("x1", 0)
        y1 = quad.get("y1", 0)
        x2 = quad.get("x2", x1 + 100)
        y2 = quad.get("y2", y1)
        x3 = quad.get("x3", x2)
        y3 = quad.get("y3", y2 + 20)
        x4 = quad.get("x4", x1)
        y4 = quad.get("y4", y3)

        # White background for the text region
        draw.rectangle([x1, y1, x3, y3], fill="white")
        # Draw translated text
        draw.text((x1 + 2, y1 + 2), translated, fill="black")

    # Encode back to base64
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")

    return OcrRenderResponse(image=f"data:image/png;base64,{encoded}")
