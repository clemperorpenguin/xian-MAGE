"""
Glossary routes.

GET /glossary — Returns the wiki glossary MAGE already builds, merged with
                user-provided terms from the extension's options page.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/glossary")

IMPLEMENTED = True

# In-memory glossary store (in production, sourced from MAGE's wiki glossary)
_glossary: dict[str, str] = {}


class GlossaryEntry(BaseModel):
    source: str
    target: str


class GlossaryResponse(BaseModel):
    terms: dict[str, str]  # source → target
    epoch: int = 0


@router.get("", response_model=GlossaryResponse)
async def get_glossary():
    """
    Return the current glossary.

    In production, this loads from MAGE's wiki glossary via
    `xian.vl_processor.VLProcessor.load_glossary_from_wiki` and merges with
    user overrides from the extension's options page.
    """
    # Try to load from MAGE's wiki glossary
    try:
        from xian.vl_processor import VLProcessor
        proc = VLProcessor()
        wiki_terms = proc.load_glossary_from_wiki()
        _glossary.update(wiki_terms)
    except ImportError:
        # Fallback: use built-in sample terms
        _glossary.setdefault("", "")
        if not _glossary:
            _glossary["user"] = "利用者"
            _glossary["server"] = "サーバー"
            _glossary["database"] = "データベース"
            _glossary["network"] = "ネットワーク"
            _glossary["application"] = "アプリケーション"

    return GlossaryResponse(terms=_glossary, epoch=hash(tuple(sorted(_glossary.items()))))


@router.post("")
async def update_glossary(entry: GlossaryEntry):
    """Add or update a single glossary entry."""
    _glossary[entry.source] = entry.target
    return {"status": "ok"}


@router.delete("/{source}")
async def delete_glossary(source: str):
    """Remove a glossary entry."""
    _glossary.pop(source, None)
    return {"status": "ok"}
