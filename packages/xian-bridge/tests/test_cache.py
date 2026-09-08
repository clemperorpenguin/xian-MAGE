"""
Tests for cache routes.
"""

from fastapi.testclient import TestClient
from xian_bridge.app import create_app

app = create_app()
client = TestClient(app, base_url="http://127.0.0.1")


def test_cache_miss():
    """Cache miss should return found=false."""
    resp = client.get("/cache", params={
        "source_text": "nonexistent",
        "source_lang": "Auto",
        "target_lang": "English",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False


def test_cache_store_and_lookup():
    """Store an entry, then look it up."""
    # Store
    resp = client.post("/cache", json={
        "entries": [{
            "source_text": "Hello",
            "source_lang": "Auto",
            "target_lang": "English",
            "translated": "Bonjour",
            "epoch": 0,
        }],
    })
    assert resp.status_code == 200
    assert resp.json()["stored"] == 1

    # Lookup
    resp = client.get("/cache", params={
        "source_text": "Hello",
        "source_lang": "Auto",
        "target_lang": "English",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert data["translated"] == "Bonjour"


def test_cache_epoch_mismatch():
    """Stale entries (epoch < caller epoch) should be ignored."""
    # Store with epoch 0
    resp = client.post("/cache", json={
        "entries": [{
            "source_text": "test",
            "source_lang": "Auto",
            "target_lang": "English",
            "translated": "test_translated",
            "epoch": 0,
        }],
    })
    assert resp.status_code == 200

    # Lookup with epoch 1 — should miss
    resp = client.get("/cache", params={
        "source_text": "test",
        "source_lang": "Auto",
        "target_lang": "English",
        "epoch": 1,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False
