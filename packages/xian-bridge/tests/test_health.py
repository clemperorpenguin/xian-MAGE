"""
Test the health endpoint — the probe MASHA uses at startup.
"""

from xian_bridge.app import create_app


async def test_health_returns_version():
    app = create_app()
    # FastAPI TestClient would be better; for now a basic import check
    assert app.title == "Xian Bridge"
