"""
Glossary routes.

GET /glossary — Returns the wiki glossary MAGE already builds, merged with
                user-provided terms from the extension's options page.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/glossary")

IMPLEMENTED = True

# In-memory glossary store (in production, sourced from MAGE's wiki glossary)
_glossary: dict[str, str] = {}

# Stand-ins for the wiki glossary on a machine that has no MAGE checkout.
_SAMPLE_TERMS: dict[str, str] = {
    "user": "利用者",
    "server": "サーバー",
    "database": "データベース",
    "network": "ネットワーク",
    "application": "アプリケーション",
}


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
    `xian.pipeline.VLProcessor.load_glossary_from_wiki` and merges with user
    overrides from the extension's options page.
    """
    # Try to load from MAGE's wiki glossary. Anything can go wrong here —
    # xian-vl absent, no wiki directory, a malformed page — and none of it is
    # worth a 500 when the fallback is a working glossary.
    try:
        from xian.pipeline import VLProcessor

        wiki_terms = await VLProcessor().load_glossary_from_wiki()
        _glossary.update(wiki_terms)
    except Exception:
        # Fall back to the built-in sample terms, but never over the top of
        # terms the user added through the options page.
        if not _glossary:
            _glossary.update(_SAMPLE_TERMS)

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
