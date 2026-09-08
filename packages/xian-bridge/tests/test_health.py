"""
Test the health endpoint — the probe MASHA uses at startup — and the guards
that keep the bridge out of reach of ordinary web pages.
"""

import pytest
from fastapi.testclient import TestClient

from xian_bridge.app import DEFAULT_EXTENSION_ORIGINS, create_app
from xian_bridge.routes import documents, ocr


@pytest.fixture()
def client():
    # base_url fixes the Host header to a loopback name the app accepts.
    with TestClient(create_app(), base_url="http://127.0.0.1") as test_client:
        yield test_client


def test_health_returns_version(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == "1.0.0"


def test_health_reports_only_implemented_backends(client):
    """A capability MASHA is told about must be one it can actually call."""
    body = client.get("/health").json()
    assert body["ocr"] == ocr.IMPLEMENTED
    assert body["documents"] == documents.IMPLEMENTED

    # Whatever /health advertises, the routes must agree.
    if not body["ocr"]:
        assert client.post("/ocr", json={"image": ""}).status_code == 501
    if not body["documents"]:
        payload = {"source_lang": "Auto", "target_lang": "English"}
        assert client.post("/documents", json=payload).status_code == 501


def test_extension_origin_is_allowed(client):
    origin = sorted(DEFAULT_EXTENSION_ORIGINS)[0]
    response = client.get("/health", headers={"Origin": origin})
    assert response.status_code == 200


def test_web_page_origin_is_rejected(client):
    """CORS lets a simple POST through; the origin guard is what stops it."""
    response = client.post(
        "/cache",
        headers={"Origin": "https://evil.example", "Content-Type": "text/plain"},
        content="[]",
    )
    assert response.status_code == 403


def test_rebound_host_is_rejected():
    """A DNS name resolving to 127.0.0.1 carries its own Host header."""
    with TestClient(create_app(), base_url="http://rebind.evil.example") as rebound:
        assert rebound.get("/health").status_code == 400


def test_configured_extension_origin_is_allowed(monkeypatch):
    packed = "chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef"
    monkeypatch.setenv("MASHA_EXTENSION_ORIGINS", packed)
    with TestClient(create_app(), base_url="http://127.0.0.1") as configured:
        assert configured.get("/health", headers={"Origin": packed}).status_code == 200
