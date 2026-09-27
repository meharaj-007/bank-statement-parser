import math
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, case, cast, func, select
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Transaction
from ...schemas import Pagination, TransactionOut, TransactionsResponse, TransactionTotals
from ..deps import get_statement_or_404
from ..errors import APIError
from .statements import escape_like

router = APIRouter()


class TransactionFilters:
    """Query params shared by the per-statement and global transaction endpoints."""

    def __init__(
        self,
        page: int = Query(1, ge=1),
        limit: int = Query(50, ge=1, le=1000),
        type: Optional[Literal['credit', 'debit']] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        search: Optional[str] = None,
        sort_by: Literal['date', 'amount'] = 'date',
        sort_order: Literal['asc', 'desc'] = 'asc',
    ):
        self.page = page
        self.limit = limit
        self.type = type
        self.date_from = date_from
        self.date_to = date_to
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.search = search
        self.sort_by = sort_by
        self.sort_order = sort_order

    def conditions(self):
        conditions = []
        if self.type:
            conditions.append(Transaction.transaction_type == self.type)
        if self.date_from:
            conditions.append(Transaction.transaction_date >= self.date_from)
        if self.date_to:
            conditions.append(Transaction.transaction_date <= self.date_to)
        if self.min_amount is not None:
            conditions.append(Transaction.amount >= self.min_amount)
        if self.max_amount is not None:
            conditions.append(Transaction.amount <= self.max_amount)
        if self.search:
            conditions.append(
                cast(Transaction.data, String).ilike(f"%{escape_like(self.search)}%", escape='\\')
            )
        return conditions

    def ordering(self):
        primary = Transaction.amount if self.sort_by == 'amount' else Transaction.transaction_date
        # Printed order breaks ties, so same-day rows stay as on the statement
        columns = [primary, Transaction.statement_id, Transaction.row_index]
        return [c.desc() for c in columns] if self.sort_order == 'desc' else [c.asc() for c in columns]


def paginated_transactions(db: Session, filters: TransactionFilters, conditions) -> TransactionsResponse:
    total = db.scalar(select(func.count()).select_from(Transaction).where(*conditions)) or 0

    rows = db.scalars(
        select(Transaction)
        .where(*conditions)
        .order_by(*filters.ordering())
        .offset((filters.page - 1) * filters.limit)
        .limit(filters.limit)
    ).all()

    total_credit, total_debit = db.execute(
        select(
            func.coalesce(func.sum(case((Transaction.transaction_type == 'credit', Transaction.amount))), 0),
            func.coalesce(func.sum(case((Transaction.transaction_type == 'debit', Transaction.amount))), 0),
        ).where(*conditions)
    ).one()

    return TransactionsResponse(
        transactions=[TransactionOut.model_validate(row) for row in rows],
        pagination=Pagination(
            page=filters.page, limit=filters.limit, total=total, pages=math.ceil(total / filters.limit)
        ),
        summary=TransactionTotals(total_credit=total_credit, total_debit=total_debit, net=total_credit - total_debit),
    )


@router.get("/statements/{statement_id}/transactions", response_model=TransactionsResponse)
def get_statement_transactions(
    statement_id: int,
    filters: TransactionFilters = Depends(),
    db: Session = Depends(get_db),
):
    """Transactions for one statement. `summary` totals cover all rows matching the filters."""
    get_statement_or_404(db, statement_id)
    conditions = [Transaction.statement_id == statement_id, *filters.conditions()]
    return paginated_transactions(db, filters, conditions)


@router.get("/transactions", response_model=TransactionsResponse)
def search_all_transactions(
    filters: TransactionFilters = Depends(),
    statement_ids: Optional[str] = Query(None, description="Comma-separated statement IDs"),
    db: Session = Depends(get_db),
):
    """Search transactions across all statements."""
    conditions = filters.conditions()
    if statement_ids:
        try:
            ids = [int(sid) for sid in statement_ids.split(',') if sid.strip()]
        except ValueError:
            raise APIError(400, "Invalid statement_ids format")
        conditions.append(Transaction.statement_id.in_(ids))
    return paginated_transactions(db, filters, conditions)
