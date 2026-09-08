"""
Tests for OCR routes.
"""

import pytest
from fastapi.testclient import TestClient
from xian_bridge.app import create_app
from xian_bridge.routes import ocr
import base64
from PIL import Image
import io

app = create_app()
client = TestClient(app, base_url="http://127.0.0.1")

# The detection endpoint needs xian-vl[ocr]; the render endpoint is pure PIL
# and works either way.
needs_engine = pytest.mark.skipif(
    not ocr.IMPLEMENTED, reason="xian-vl[ocr] engine not installed"
)


@pytest.mark.skipif(ocr.IMPLEMENTED, reason="engine is installed")
def test_ocr_reports_501_without_an_engine():
    """No engine must mean a refusal, never a placeholder block to translate."""
    resp = client.post(
        "/ocr",
        json={"image": "", "source_lang": "Auto", "mode": "text"},
    )
    assert resp.status_code == 501


@needs_engine
def test_ocr_validates_image_format():
    """Invalid base64 should return 400."""
    resp = client.post(
        "/ocr",
        json={"image": "not-base64", "source_lang": "Auto", "mode": "text"},
    )
    assert resp.status_code == 400


@needs_engine
def test_ocr_returns_block_structure():
    """A valid image should return blocks with quads."""
    # Generate a 10x10 white PNG
    from PIL import Image
    import io
    img = Image.new('RGB', (10, 10), color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    valid_png = base64.b64encode(buf.getvalue()).decode('utf-8')

    resp = client.post(
        "/ocr",
        json={"image": f"data:image/png;base64,{valid_png}", "source_lang": "Auto", "mode": "text"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "blocks" in data
    assert "size" in data
    assert data["size"]["width"] == 10
    assert data["size"]["height"] == 10


def test_ocr_render_returns_image():
    """Render endpoint should return a base64 image."""
    # Generate a 100x100 white PNG
    from PIL import Image
    import io
    img = Image.new('RGB', (100, 100), color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    valid_png = base64.b64encode(buf.getvalue()).decode('utf-8')

    resp = client.post(
        "/ocr/render",
        json={
            "image": f"data:image/png;base64,{valid_png}",
            "blocks": [{"quad": {"x1": 0, "y1": 0, "x2": 100, "y2": 0, "x3": 100, "y3": 20, "x4": 0, "y4": 20}, "translated": "Hello"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "image" in data
    assert data["image"].startswith("data:image/png;base64,")
