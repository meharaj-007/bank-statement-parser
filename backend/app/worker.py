"""
Celery worker for statement processing.

Run with:
    celery -A app.worker worker --loglevel=info
"""
import logging

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import setup_logging as celery_setup_logging

from .core.config import settings
from .core.logging import setup_logging

logger = logging.getLogger(__name__)

celery_app = Celery("bank_statement_parser", broker=settings.CELERY_BROKER_URL)
celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    # Re-deliver if the worker dies mid-statement
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.TASK_TIME_LIMIT,
    task_soft_time_limit=settings.TASK_TIME_LIMIT - 60,
    broker_transport_options={"visibility_timeout": settings.TASK_TIME_LIMIT + 300},
    broker_connection_retry_on_startup=True,
)


@celery_setup_logging.connect
def _configure_logging(**_):
    setup_logging()


@celery_app.task(name="statements.process")
def process_statement_task(statement_id: int) -> bool:
    from .services.statement_processor import StatementProcessor, mark_statement_failed

    try:
        return StatementProcessor().process(statement_id)
    except SoftTimeLimitExceeded:
        mark_statement_failed(statement_id, f"Processing exceeded {settings.TASK_TIME_LIMIT}s time limit")
    except Exception as e:
        # e.g. missing GROQ_API_KEY; without this the statement would stay pending
        logger.exception(f"Statement {statement_id} could not be processed: {e}")
        mark_statement_failed(statement_id, str(e) or type(e).__name__)
    return False
