"""PDF documents: upload, background indexing, listing, and searching (no Gemini needed).

Uploaded PDFs go into the same documents/ folder the desktop Jarvis reads, so a PDF uploaded
through the API can also be asked about by voice, and the other way round.
"""
import logging
import re
from pathlib import Path

import rag
from backend import config
from backend.cache import TTLCache
from backend.database import connect
from backend.errors import BadRequestError, NotFoundError, PayloadTooLargeError
from backend.repositories import UploadRepository
from backend.services.jarvis import RAG_LOCK

logger = logging.getLogger("jarvis.documents")

PDF_SIGNATURE = b"%PDF-"  # every real PDF file starts with these bytes
DOCUMENTS_KEY = "documents"


def safe_filename(name: str) -> str:
    """Never trust a filename from the internet: "../../Windows/evil.pdf" must not escape documents/."""
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    if not name.lower().endswith(".pdf") or len(name) < 5:
        raise BadRequestError("Only .pdf files can be uploaded.")
    return name[-120:]


class DocumentService:
    def __init__(self, uploads: UploadRepository, cache: TTLCache):
        self.uploads = uploads
        self.cache = cache
        self.db = uploads.db

    def list_documents(self) -> list[dict]:
        docs = self.cache.get(DOCUMENTS_KEY)
        if docs is None:  # cache miss: ask ChromaDB, then remember the answer
            docs = rag.list_documents()["documents"]
            self.cache.set(DOCUMENTS_KEY, docs, config.DOCUMENTS_CACHE_SECONDS)
        return docs

    def save_upload(self, filename: str, content: bytes, owner_id: int):
        name = safe_filename(filename)
        if len(content) > config.MAX_UPLOAD_BYTES:
            raise PayloadTooLargeError(f"The PDF is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
        if not content.startswith(PDF_SIGNATURE):  # check the content, not just the name
            raise BadRequestError("This file is not a real PDF.")
        rag.DOCS_DIR.mkdir(exist_ok=True)
        (rag.DOCS_DIR / name).write_bytes(content)
        with self.db:
            return self.uploads.create(name, owner_id)

    def get_upload(self, upload_id: int):
        upload = self.uploads.get(upload_id)
        if upload is None:
            raise NotFoundError(f"Upload {upload_id} not found.")
        return upload

    def search(self, query: str, intent: str) -> dict:
        with RAG_LOCK:
            try:
                return rag.search_documents(query, intent)
            finally:
                rag.start_turn()  # this search isn't part of a chat answer: drop its trace


def index_upload(upload_id: int, filename: str, cache: TTLCache) -> None:
    """Runs AFTER the 202 response was sent (FastAPI BackgroundTasks).

    It opens its own database connection, because the request's connection is closed by now.
    """
    db = connect()
    uploads = UploadRepository(db)
    try:
        with db:
            uploads.set_status(upload_id, "indexing")
        chunks = rag.index_pdf(rag.DOCS_DIR / filename, log=logger.info)
        indexed = rag._get_collection().get(where={"source": filename}, limit=1)["ids"]
        with db:
            if indexed:
                uploads.set_status(upload_id, "ready", chunks=chunks or None)
            else:
                uploads.set_status(upload_id, "failed", error="No readable text (it may be a scanned PDF).")
        cache.delete(DOCUMENTS_KEY)  # cache invalidation: the list of documents just changed
    except Exception as e:
        logger.exception("Indexing upload %s failed", upload_id)
        with db:
            uploads.set_status(upload_id, "failed", error=str(e)[:500])
    finally:
        db.close()
