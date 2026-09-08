"""
Document routes — long-running translation jobs via Lemonade jobs API.

POST /documents              — Start a new document translation job
GET  /documents/{id}         — Job status / progress
POST /documents/{id}/pause   — Pause a running job
POST /documents/{id}/resume  — Resume a paused job
POST /documents/{id}/cancel  — Cancel and discard a job
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

router = APIRouter(prefix="/documents")

# True once the Luduan job pipeline is wired in place of the 501 stubs below.
# /health reports this verbatim, so the two can never drift apart.
IMPLEMENTED = False


class DocumentRequest(BaseModel):
    source_lang: str
    target_lang: str
    bilingual: bool = True


class DocumentResponse(BaseModel):
    job_id: str


class DocumentStatus(BaseModel):
    status: Literal["queued", "running", "paused", "done", "failed"]
    progress: float = 0.0  # 0..1
    pages_done: int = 0
    download_url: Optional[str] = None


@router.post("", response_model=DocumentResponse)
async def start_document(_request: DocumentRequest):
    """Start a document translation job. File is sent as multipart."""
    # Stub — will delegate to Luduan pipeline
    raise HTTPException(status_code=501, detail="Document processing not yet implemented")


@router.get("/{job_id}", response_model=DocumentStatus)
async def get_document(job_id: str):
    """Poll job progress."""
    # Stub
    raise HTTPException(status_code=501, detail="Document processing not yet implemented")


@router.post("/{job_id}/pause")
async def pause_document(job_id: str):
    """Pause a running job."""
    raise HTTPException(status_code=501, detail="Document processing not yet implemented")


@router.post("/{job_id}/resume")
async def resume_document(job_id: str):
    """Resume a paused job."""
    raise HTTPException(status_code=501, detail="Document processing not yet implemented")


@router.post("/{job_id}/cancel")
async def cancel_document(job_id: str):
    """Cancel and discard a job."""
    raise HTTPException(status_code=501, detail="Document processing not yet implemented")
