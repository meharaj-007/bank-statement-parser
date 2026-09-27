import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base

Money = Numeric(15, 2)


def utcnow() -> datetime:
    return datetime.utcnow()


class ProcessingStatus(str, enum.Enum):
    """Processing status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class BankStatement(Base):
    """Uploaded PDF and its processing state."""
    __tablename__ = "bank_statements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Path relative to UPLOAD_DIR
    filename: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_size: Mapped[int] = mapped_column(Integer)
    upload_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, values_callable=lambda e: [m.value for m in e], native_enum=False),
        default=ProcessingStatus.PENDING,
        index=True,
    )
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    page_count: Mapped[Optional[int]] = mapped_column(Integer)

    # Extraction metadata
    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    raw_extraction_data: Mapped[Optional[List[Any]]] = mapped_column(JSON)  # Per-page LLM output
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON)
    confidence_scores: Mapped[Optional[dict]] = mapped_column(JSON)
    processing_logs: Mapped[List[Any]] = mapped_column(JSON, default=list)
    validation_errors: Mapped[Optional[dict]] = mapped_column(JSON)

    customer_details: Mapped[Optional["CustomerDetails"]] = relationship(
        back_populates="statement", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )
    bank_details: Mapped[Optional["BankDetails"]] = relationship(
        back_populates="statement", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )
    transactions: Mapped[List["Transaction"]] = relationship(
        back_populates="statement", cascade="all, delete-orphan", passive_deletes=True
    )
    transaction_schema: Mapped[Optional["TransactionSchema"]] = relationship(
        back_populates="statement", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self):
        return f"<BankStatement(id={self.id}, filename={self.original_filename}, status={self.status})>"


class CustomerDetails(Base):
    """Account holder details extracted from the statement."""
    __tablename__ = "customer_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="CASCADE"), unique=True
    )
    account_holder_name: Mapped[Optional[str]] = mapped_column(String(255))
    account_number: Mapped[Optional[str]] = mapped_column(String(100))  # Masked when MASK_PII is on
    additional_info: Mapped[dict] = mapped_column(JSON, default=dict)

    statement: Mapped[BankStatement] = relationship(back_populates="customer_details")


class BankDetails(Base):
    """Bank and statement period details."""
    __tablename__ = "bank_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="CASCADE"), unique=True
    )
    bank_name: Mapped[Optional[str]] = mapped_column(String(255))
    statement_period_start: Mapped[Optional[date]] = mapped_column(Date)
    statement_period_end: Mapped[Optional[date]] = mapped_column(Date)
    opening_balance: Mapped[Optional[Decimal]] = mapped_column(Money)
    closing_balance: Mapped[Optional[Decimal]] = mapped_column(Money)
    currency: Mapped[Optional[str]] = mapped_column(String(10))
    additional_info: Mapped[dict] = mapped_column(JSON, default=dict)

    statement: Mapped[BankStatement] = relationship(back_populates="bank_details")


class Transaction(Base):
    """One transaction row. `data` keeps the original columns as extracted."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="CASCADE"), index=True
    )
    transaction_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Money, index=True)
    transaction_type: Mapped[Optional[str]] = mapped_column(String(20), index=True)  # credit, debit or null
    balance: Mapped[Optional[Decimal]] = mapped_column(Money)
    data: Mapped[dict] = mapped_column(JSON)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    # Position across the whole statement, preserves the printed order
    row_index: Mapped[int] = mapped_column(Integer)

    statement: Mapped[BankStatement] = relationship(back_populates="transactions")

    __table_args__ = (
        Index("idx_statement_date", "statement_id", "transaction_date"),
        Index("idx_statement_type", "statement_id", "transaction_type"),
    )


class TransactionSchema(Base):
    """Detected transaction columns for a statement, used for dynamic rendering."""
    __tablename__ = "transaction_schemas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="CASCADE"), unique=True
    )
    columns: Mapped[List[str]] = mapped_column(JSON)
    column_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    detected_bank_format: Mapped[Optional[str]] = mapped_column(String(100))

    statement: Mapped[BankStatement] = relationship(back_populates="transaction_schema")
