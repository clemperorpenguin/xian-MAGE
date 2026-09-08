"""
Glossary route — canonical source→target term mappings.

GET /glossary — Returns the wiki glossary MAGE builds via
                VLProcessor.load_glossary_from_wiki, merged with any user
                overrides from the extension's options page.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/glossary")


@router.get("")
async def glossary():
    """
    Return the canonical glossary as {source_term: target_term} pairs.

    Terms are sorted longest-first so MASHA can apply them greedily — a longer
    match is more specific and should win over a shorter one.
    """
    # Stub — will load from MAGE's glossary store
    return {
        "terms": {},
        "epoch": 0,
    }
