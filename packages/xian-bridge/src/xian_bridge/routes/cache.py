"""
Cache routes — shared translation cache with MAGE's session store.

GET  /cache?source_text=...&source_lang=...&target_lang=...  — Lookup
POST /cache  — Batch store translations
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import time
import sqlite3
import os

router = APIRouter(prefix="/cache")

IMPLEMENTED = True


class CacheEntry(BaseModel):
    source_text: str
    source_lang: str
    target_lang: str
    translated: str
    epoch: int = 0


class CacheLookupResponse(BaseModel):
    found: bool = False
    translated: Optional[str] = None
    epoch: Optional[int] = None


class CacheStoreRequest(BaseModel):
    entries: list[CacheEntry]


# Path to MAGE's session store database
def _db_path() -> str:
    """Get the path to the shared session store database."""
    data_dir = os.environ.get("XIAN_DATA_DIR", os.path.expanduser("~/.local/share/xian"))
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "session_store.db")


def _ensure_table(db_path: str):
    """Ensure the translations table exists."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                source_text  TEXT NOT NULL,
                source_lang  TEXT NOT NULL,
                target_lang  TEXT NOT NULL,
                translated   TEXT NOT NULL,
                epoch        INTEGER NOT NULL,
                hits         INTEGER NOT NULL DEFAULT 0,
                updated_at   REAL NOT NULL,
                PRIMARY KEY (source_text, source_lang, target_lang)
            )
        """)
        conn.commit()
    finally:
        conn.close()


@router.get("", response_model=CacheLookupResponse)
async def cache_lookup(
    source_text: str = Query(...),
    source_lang: str = Query("Auto"),
    target_lang: str = Query("English"),
    epoch: int = Query(0),
):
    """
    Look up a translation in the shared cache.

    Returns `found=false` on miss.  Rows with an epoch older than the
    caller's current epoch are treated as stale and ignored.
    """
    db_path = _db_path()
    _ensure_table(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT translated, epoch FROM translations "
            "WHERE source_text = ? AND source_lang = ? AND target_lang = ?",
            (source_text, source_lang, target_lang),
        )
        row = cursor.fetchone()
        if row is None:
            return CacheLookupResponse(found=False)

        translated, stored_epoch = row

        # Stale check: if caller's epoch > stored epoch, treat as miss
        if epoch > stored_epoch:
            return CacheLookupResponse(found=False)

        # Increment hits
        cursor.execute(
            "UPDATE translations SET hits = hits + 1, updated_at = ? "
            "WHERE source_text = ? AND source_lang = ? AND target_lang = ?",
            (time.time(), source_text, source_lang, target_lang),
        )
        conn.commit()

        return CacheLookupResponse(
            found=True,
            translated=translated,
            epoch=stored_epoch,
        )
    finally:
        conn.close()


@router.post("")
async def cache_store(request: CacheStoreRequest):
    """
    Batch-store translations into the shared cache.
    """
    db_path = _db_path()
    _ensure_table(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        now = time.time()

        for entry in request.entries:
            cursor.execute("""
                INSERT INTO translations (source_text, source_lang, target_lang,
                                          translated, epoch, hits, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(source_text, source_lang, target_lang)
                DO UPDATE SET translated = ?, epoch = ?, hits = hits + 1, updated_at = ?
            """, (
                entry.source_text, entry.source_lang, entry.target_lang,
                entry.translated, entry.epoch, now,
                entry.translated, entry.epoch, now,
            ))

        conn.commit()
        return {"stored": len(request.entries)}
    finally:
        conn.close()
