import logging

from sqlalchemy.orm import Session

from ..models import BankStatement, ProcessingStatus
from .errors import APIError

logger = logging.getLogger(__name__)


def get_statement_or_404(db: Session, statement_id: int) -> BankStatement:
    statement = db.get(BankStatement, statement_id)
    if not statement:
        raise APIError(404, "Statement not found")
    return statement


def enqueue_processing(db: Session, statement: BankStatement) -> None:
    """Queue a statement for the worker. Marks it failed if the broker is unreachable."""
    from ..worker import process_statement_task

    try:
        process_statement_task.apply_async(
            args=[statement.id],
            retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.5},
        )
    except Exception as e:
        logger.error(f"Could not queue statement {statement.id}: {e}")
        statement.status = ProcessingStatus.FAILED
        statement.error_message = "Could not queue processing. Is Redis running?"
        db.commit()
        raise APIError(503, statement.error_message, statement_id=statement.id)
