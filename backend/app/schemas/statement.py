from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Pagination(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class UploadResponse(BaseModel):
    success: bool
    statement_id: int
    message: str


class StatementListItem(BaseModel):
    id: int
    filename: str
    upload_date: datetime
    status: str
    page_count: Optional[int]
    bank_name: Optional[str]
    account_number: Optional[str]
    period_start: Optional[date]
    period_end: Optional[date]
    transaction_count: int


class StatementListResponse(BaseModel):
    statements: List[StatementListItem]
    pagination: Pagination


class StatementDetailResponse(BaseModel):
    id: int
    filename: str
    upload_date: datetime
    status: str
    page_count: Optional[int]
    customer_details: Optional[Dict[str, Any]]
    bank_details: Optional[Dict[str, Any]]
    transaction_count: int
    error_message: Optional[str]


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_date: Optional[date]
    amount: Optional[Decimal]
    transaction_type: Optional[str]
    balance: Optional[Decimal]
    data: Dict[str, Any]
    page_number: Optional[int]


class TransactionTotals(BaseModel):
    total_credit: Decimal
    total_debit: Decimal
    net: Decimal


class TransactionsResponse(BaseModel):
    transactions: List[TransactionOut]
    pagination: Pagination
    summary: TransactionTotals


class StatementSummaryResponse(BaseModel):
    statement_id: int
    total_transactions: int
    total_credit: Decimal
    total_debit: Decimal
    net: Decimal
    credit_count: int
    debit_count: int
    opening_balance: Optional[Decimal]
    closing_balance: Optional[Decimal]


class ColumnMetadata(BaseModel):
    type: Literal['date', 'currency', 'text', 'number']
    display_name: str


class TransactionSchemaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    columns: List[str]
    column_metadata: Dict[str, ColumnMetadata]
    detected_bank_format: Optional[str]


class SchemaUpdateRequest(BaseModel):
    column_metadata: Dict[str, ColumnMetadata]


class SchemaUpdateResponse(BaseModel):
    success: bool
    message: str
    # `schema` would shadow a BaseModel attribute
    schema_: TransactionSchemaResponse = Field(serialization_alias='schema')


class ProcessingTimes(BaseModel):
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]


class StatementMetadataResponse(BaseModel):
    statement_id: int
    model_used: Optional[str]
    raw_extraction_data: List[Any]
    token_usage: Dict[str, Any]
    confidence_scores: Dict[str, Any]
    processing_logs: List[Any]
    validation_errors: Dict[str, Any]
    transaction_schema: Optional[TransactionSchemaResponse]
    processing_times: ProcessingTimes
    page_count: Optional[int]
    status: str
    error_message: Optional[str]
