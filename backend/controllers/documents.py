from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile

from backend import config
from backend.dependencies import api_key_header, current_owner, get_document_service
from backend.schemas import DocumentOut, SearchQuery, SearchResult, UploadOut
from backend.services.document_service import DocumentService, index_upload

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[Depends(api_key_header)])


@router.get("", response_model=list[DocumentOut])
def list_documents(service: DocumentService = Depends(get_document_service)):
    """The PDFs Jarvis can search (cached)."""
    return service.list_documents()


@router.post("", status_code=202, response_model=UploadOut)
def upload_document(background: BackgroundTasks, file: UploadFile = File(...),
                    owner: int = Depends(current_owner), service: DocumentService = Depends(get_document_service)):
    """Upload a PDF. Answers 202 Accepted straight away; indexing runs in the background.
    Check its progress with GET /api/documents/uploads/{id}."""
    content = file.file.read(config.MAX_UPLOAD_BYTES + 1)  # +1 byte tells us if it's too big
    upload = service.save_upload(file.filename or "", content, owner)
    background.add_task(index_upload, upload["id"], upload["filename"], service.cache)
    return dict(upload)


@router.get("/uploads/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: int, service: DocumentService = Depends(get_document_service)):
    """Status of an upload: pending, indexing, ready or failed."""
    return dict(service.get_upload(upload_id))


@router.get("/search", response_model=SearchResult)
def search_documents(query: Annotated[SearchQuery, Query()], service: DocumentService = Depends(get_document_service)):
    """Search your PDFs directly: hybrid search + reranking + compression. Uses no Gemini quota."""
    return service.search(query.q, query.intent)
