import logging

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import BankStatement, ProcessingStatus
from ...schemas import UploadResponse
from ...services.storage_service import NotAPDF, StorageService, UploadTooLarge, safe_display_name
from ..deps import enqueue_processing
from ..errors import APIError

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=UploadResponse, status_code=202)
def upload_statement(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload a bank statement PDF. Processing runs in the Celery worker; poll
    GET /statements/{id} until status is completed or failed.

    Uploading a file that already exists returns 409 with `existing_statement_id`,
    unless the earlier attempt failed, in which case it is reprocessed.
    """
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise APIError(400, "Only PDF files are allowed")

    storage = StorageService()
    try:
        stored = storage.receive(file.file)
    except NotAPDF as e:
        raise APIError(400, str(e))
    except UploadTooLarge as e:
        raise APIError(413, str(e))

    existing = db.scalar(select(BankStatement).where(BankStatement.file_hash == stored.hash))
    if existing:
        if existing.status != ProcessingStatus.FAILED:
            storage.discard(stored)
            raise APIError(409, "This file has already been uploaded", existing_statement_id=existing.id)

        if storage.absolute_path(existing.filename).exists():
            storage.discard(stored)
        else:
            existing.filename = storage.commit(stored)
        existing.status = ProcessingStatus.PENDING
        existing.error_message = None
        db.commit()
        enqueue_processing(db, existing)
        return UploadResponse(
            success=True,
            statement_id=existing.id,
            message="Previous attempt failed. Reprocessing the statement.",
        )

    statement = BankStatement(
        filename=storage.commit(stored),
        original_filename=safe_display_name(file.filename),
        file_hash=stored.hash,
        file_size=stored.size,
        status=ProcessingStatus.PENDING,
        processing_logs=[],
    )
    db.add(statement)
    try:
        db.commit()
    except IntegrityError:
        # Same file uploaded concurrently; the stored copy is shared by hash, so keep it
        db.rollback()
        winner = db.scalar(select(BankStatement).where(BankStatement.file_hash == stored.hash))
        raise APIError(409, "This file has already been uploaded", existing_statement_id=winner.id if winner else None)

    enqueue_processing(db, statement)
    logger.info(f"Statement {statement.id} queued for processing")

    return UploadResponse(
        success=True,
        statement_id=statement.id,
        message="File uploaded. Processing started.",
    )
