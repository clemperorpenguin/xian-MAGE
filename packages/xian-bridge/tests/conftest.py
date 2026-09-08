"""
Isolation for the bridge's tests.

The cache route stores into MAGE's real session store
(``~/.local/share/xian/session_store.db``) unless ``XIAN_DATA_DIR`` says
otherwise, and the document routes write into the system temp directory. A test
run must not leave fixtures like "Hello → Bonjour" in a store the bridge will
later serve to the extension as genuine cache hits.
"""

import tempfile

import pytest

from xian_bridge.routes import documents, glossary


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XIAN_DATA_DIR", str(tmp_path / "xian-data"))

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setattr(tempfile, "tempdir", str(tmpdir))

    # Both stores are module-level dicts: without this a job or a glossary term
    # from one test is still there in the next.
    documents._jobs.clear()
    glossary._glossary.clear()
    yield
