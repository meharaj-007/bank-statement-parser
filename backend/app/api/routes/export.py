import csv
import logging
from io import StringIO

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import ProcessingStatus, Transaction
from ..deps import get_statement_or_404
from ..errors import APIError

router = APIRouter()
logger = logging.getLogger(__name__)


def _fmt(value) -> str:
    return "" if value is None else str(value)


@router.get("/statements/{statement_id}/csv")
def export_to_csv(statement_id: int, db: Session = Depends(get_db)):
    """
    Export a statement as CSV: header block (bank, account, period, balances),
    then every transaction with its original columns plus the parsed fields.
    """
    statement = get_statement_or_404(db, statement_id)
    if statement.status != ProcessingStatus.COMPLETED:
        raise APIError(400, "Statement processing not completed")

    bank = statement.bank_details
    customer = statement.customer_details
    columns = statement.transaction_schema.columns if statement.transaction_schema else []
    transactions = db.scalars(
        select(Transaction).where(Transaction.statement_id == statement_id).order_by(Transaction.row_index)
    ).all()

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(["Bank Statement Export"])
    writer.writerow(["File", statement.original_filename])
    if bank:
        writer.writerow(["Bank Name", _fmt(bank.bank_name)])
        writer.writerow(["Currency", _fmt(bank.currency)])
        writer.writerow(["Statement Period", f"{_fmt(bank.statement_period_start)} to {_fmt(bank.statement_period_end)}"])
        writer.writerow(["Opening Balance", _fmt(bank.opening_balance)])
        writer.writerow(["Closing Balance", _fmt(bank.closing_balance)])
    if customer:
        writer.writerow(["Account Holder", _fmt(customer.account_holder_name)])
        writer.writerow(["Account Number", _fmt(customer.account_number)])
    writer.writerow([])

    writer.writerow([*columns, "Parsed Date", "Parsed Amount", "Type", "Page"])
    for txn in transactions:
        writer.writerow([
            *(_fmt(txn.data.get(col)) for col in columns),
            _fmt(txn.transaction_date),
            _fmt(txn.amount),
            _fmt(txn.transaction_type),
            _fmt(txn.page_number),
        ])

    filename = f"statement_{statement_id}_{statement.upload_date:%Y%m%d}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
