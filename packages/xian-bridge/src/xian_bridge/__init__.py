"""
xian-bridge — Local bridge service for the MASHA browser extension.

Exposes OCR, document processing, glossary lookup, and a shared translation
cache over HTTP to the MASHA extension (and only the extension). Binds to
loopback only, CORS-allowlisted to extension origins.

Routes
------
GET  /health           — {version, ocr: bool, documents: bool}
POST /ocr              — OCR an image → blocks with quads
POST /ocr/render       — Inpaint translated blocks onto an image
POST /documents        — Start a long document translation job
GET  /documents/{id}   — Job status / progress
POST /documents/{id}/pause|resume|cancel — Job control
GET  /cache            — Read cached translations (batched)
POST /cache            — Write cached translations (batched)
GET  /glossary         — Canonical glossary (source→target terms)
"""

__version__ = "1.0.0"
