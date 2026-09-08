"""
Cache routes — shared translation cache with MAGE's session store.

GET  /cache?text=...&source_lang=...&target_lang=...  — Lookup a translation
POST /cache                                              — Store translations (batched)

The cache is a ``translations`` table in the SQLite database that
xian.session_store.SessionStore already owns — the same file, separate table.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/cache")


class CacheEntry(BaseModel):
    source_text: str
    source_lang: str
    target_lang: str
    translated: str
    epoch: int = 0


class CacheLookupResponse(BaseModel):
    found: bool = False
    translated: Optional[str] = None
    epoch: int = 0


@router.get("", response_model=CacheLookupResponse)
async def cache_lookup(
    text: str = Query(..., description="Source text to look up"),
    source_lang: str = Query("Auto"),
    target_lang: str = Query("English"),
):
    """Look up a cached translation."""
    # Stub — will query the shared SQLite database
    raise HTTPException(status_code=501, detail="Cache not yet implemented")


@router.post("")
async def cache_store(entries: list[CacheEntry]):
    """Store one or more translation cache entries."""
    # Stub — will write to the shared SQLite database
    raise HTTPException(status_code=501, detail="Cache not yet implemented")
