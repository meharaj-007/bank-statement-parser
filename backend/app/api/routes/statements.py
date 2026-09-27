import logging
import math
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ...core.database import get_db
from ...models import (
    BankDetails,
    BankStatement,
    CustomerDetails,
    ProcessingStatus,
    Transaction,
    TransactionSchema,
)
from ...schemas import (
    Pagination,
    SchemaUpdateRequest,
    SchemaUpdateResponse,
    StatementDetailResponse,
    StatementListItem,
    StatementListResponse,
    StatementMetadataResponse,
    StatementSummaryResponse,
    TransactionSchemaResponse,
    UploadResponse,
)
from ...services.storage_service import StorageService
from ..deps import enqueue_processing, get_statement_or_404
from ..errors import APIError

router = APIRouter()
logger = logging.getLogger(__name__)


def escape_like(term: str) -> str:
    return term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def customer_to_dict(customer: Optional[CustomerDetails]) -> Optional[Dict[str, Any]]:
    if not customer:
        return None
    return {
        **(customer.additional_info or {}),
        'account_holder_name': customer.account_holder_name,
        'account_number': customer.account_number,
    }


def bank_to_dict(bank: Optional[BankDetails]) -> Optional[Dict[str, Any]]:
    if not bank:
        return None
    return {
        **(bank.additional_info or {}),
        'bank_name': bank.bank_name,
        'statement_period_start': bank.statement_period_start,
        'statement_period_end': bank.statement_period_end,
        'opening_balance': bank.opening_balance,
        'closing_balance': bank.closing_balance,
        'currency': bank.currency,
    }


def transaction_count(db: Session, statement_id: int) -> int:
    return db.scalar(select(func.count()).where(Transaction.statement_id == statement_id)) or 0


@router.get("/statements", response_model=StatementListResponse)
def list_statements(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=1000),
    status: Optional[ProcessingStatus] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List statements, newest first. `search` matches filename, bank name or account number."""
    query = select(BankStatement)

    if status:
        query = query.where(BankStatement.status == status)

    if search:
        term = f"%{escape_like(search)}%"
        query = (
            query.outerjoin(BankDetails).outerjoin(CustomerDetails)
            .where(or_(
                BankStatement.original_filename.ilike(term, escape='\\'),
                BankDetails.bank_name.ilike(term, escape='\\'),
                CustomerDetails.account_number.ilike(term, escape='\\'),
            ))
        )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    statements = db.scalars(
        query.options(selectinload(BankStatement.bank_details), selectinload(BankStatement.customer_details))
        .order_by(BankStatement.upload_date.desc(), BankStatement.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()

    counts = dict(db.execute(
        select(Transaction.statement_id, func.count())
        .where(Transaction.statement_id.in_([s.id for s in statements]))
        .group_by(Transaction.statement_id)
    ).all()) if statements else {}

    return StatementListResponse(
        statements=[
            StatementListItem(
                id=s.id,
                filename=s.original_filename,
                upload_date=s.upload_date,
                status=s.status.value,
                page_count=s.page_count,
                bank_name=s.bank_details.bank_name if s.bank_details else None,
                account_number=s.customer_details.account_number if s.customer_details else None,
                period_start=s.bank_details.statement_period_start if s.bank_details else None,
                period_end=s.bank_details.statement_period_end if s.bank_details else None,
                transaction_count=counts.get(s.id, 0),
            )
            for s in statements
        ],
        pagination=Pagination(page=page, limit=limit, total=total, pages=math.ceil(total / limit)),
    )


@router.get("/statements/{statement_id}", response_model=StatementDetailResponse)
def get_statement(statement_id: int, db: Session = Depends(get_db)):
    """Statement details with customer and bank info. Poll this while status is pending/processing."""
    statement = get_statement_or_404(db, statement_id)
    return StatementDetailResponse(
        id=statement.id,
        filename=statement.original_filename,
        upload_date=statement.upload_date,
        status=statement.status.value,
        page_count=statement.page_count,
        customer_details=customer_to_dict(statement.customer_details),
        bank_details=bank_to_dict(statement.bank_details),
        transaction_count=transaction_count(db, statement_id),
        error_message=statement.error_message,
    )


@router.delete("/statements/{statement_id}")
def delete_statement(statement_id: int, db: Session = Depends(get_db)):
    """Delete a statement, its extracted data and the stored PDF."""
    statement = get_statement_or_404(db, statement_id)
    relative_path = statement.filename

    db.delete(statement)
    db.commit()
    StorageService().delete(relative_path)

    logger.info(f"Deleted statement {statement_id}")
    return {"success": True, "message": "Statement deleted"}


@router.post("/statements/{statement_id}/reprocess", response_model=UploadResponse, status_code=202)
def reprocess_statement(statement_id: int, db: Session = Depends(get_db)):
    """Run extraction again, replacing earlier results."""
    statement = get_statement_or_404(db, statement_id)
    if statement.status in (ProcessingStatus.PENDING, ProcessingStatus.PROCESSING):
        raise APIError(409, "Statement is already being processed")

    statement.status = ProcessingStatus.PENDING
    statement.error_message = None
    db.commit()
    enqueue_processing(db, statement)
    return UploadResponse(success=True, statement_id=statement.id, message="Reprocessing started.")


@router.get("/statements/{statement_id}/schema", response_model=TransactionSchemaResponse)
def get_statement_schema(statement_id: int, db: Session = Depends(get_db)):
    """Transaction columns and their types, for dynamic table rendering."""
    statement = get_statement_or_404(db, statement_id)
    if not statement.transaction_schema:
        return TransactionSchemaResponse(columns=[], column_metadata={}, detected_bank_format=None)
    return statement.transaction_schema


@router.put("/statements/{statement_id}/schema", response_model=SchemaUpdateResponse)
def update_statement_schema(statement_id: int, body: SchemaUpdateRequest, db: Session = Depends(get_db)):
    """Update column types and display names."""
    statement = get_statement_or_404(db, statement_id)
    schema = statement.transaction_schema
    if not schema:
        raise APIError(404, "Schema not found for this statement")

    unknown = set(body.column_metadata) - set(schema.columns)
    if unknown:
        raise APIError(400, f"Unknown columns: {', '.join(sorted(unknown))}")

    schema.column_metadata = {
        **schema.column_metadata,
        **{col: meta.model_dump() for col, meta in body.column_metadata.items()},
    }
    db.commit()

    return SchemaUpdateResponse(
        success=True,
        message="Schema updated successfully",
        schema_=TransactionSchemaResponse.model_validate(schema),
    )


@router.get("/statements/{statement_id}/summary", response_model=StatementSummaryResponse)
def get_statement_summary(statement_id: int, db: Session = Depends(get_db)):
    """Credit/debit totals and counts."""
    statement = get_statement_or_404(db, statement_id)

    is_credit = Transaction.transaction_type == 'credit'
    is_debit = Transaction.transaction_type == 'debit'
    total, credit_count, debit_count, total_credit, total_debit = db.execute(
        select(
            func.count(),
            func.count(case((is_credit, 1))),
            func.count(case((is_debit, 1))),
            func.coalesce(func.sum(case((is_credit, Transaction.amount))), 0),
            func.coalesce(func.sum(case((is_debit, Transaction.amount))), 0),
        ).where(Transaction.statement_id == statement_id)
    ).one()

    bank = statement.bank_details
    return StatementSummaryResponse(
        statement_id=statement_id,
        total_transactions=total,
        total_credit=total_credit,
        total_debit=total_debit,
        net=total_credit - total_debit,
        credit_count=credit_count,
        debit_count=debit_count,
        opening_balance=bank.opening_balance if bank else None,
        closing_balance=bank.closing_balance if bank else None,
    )


@router.get("/statements/{statement_id}/metadata", response_model=StatementMetadataResponse)
def get_statement_metadata(statement_id: int, db: Session = Depends(get_db)):
    """Raw per-page extraction, token usage, confidence scores and processing logs."""
    statement = get_statement_or_404(db, statement_id)
    started, completed = statement.processing_started_at, statement.processing_completed_at

    return StatementMetadataResponse(
        statement_id=statement_id,
        model_used=statement.model_used,
        raw_extraction_data=statement.raw_extraction_data or [],
        token_usage=statement.token_usage or {},
        confidence_scores=statement.confidence_scores or {},
        processing_logs=statement.processing_logs or [],
        validation_errors=statement.validation_errors or {},
        transaction_schema=(
            TransactionSchemaResponse.model_validate(statement.transaction_schema)
            if statement.transaction_schema else None
        ),
        processing_times={
            'started_at': started,
            'completed_at': completed,
            'duration_seconds': (completed - started).total_seconds() if started and completed else None,
        },
        page_count=statement.page_count,
        status=statement.status.value,
        error_message=statement.error_message,
    )


@router.get("/statements/{statement_id}/file")
def get_statement_file(statement_id: int, db: Session = Depends(get_db)):
    """The original PDF, displayed inline."""
    statement = get_statement_or_404(db, statement_id)
    path = StorageService().absolute_path(statement.filename)
    if not path.exists():
        logger.error(f"PDF missing for statement {statement_id}: {path}")
        raise APIError(404, "File not found")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=statement.original_filename,
        content_disposition_type="inline",
    )
