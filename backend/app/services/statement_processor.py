import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete

from ..core.config import settings
from ..core.database import SessionLocal
from ..models import (
    BankDetails,
    BankStatement,
    CustomerDetails,
    ProcessingStatus,
    Transaction,
    TransactionSchema,
)
from .pdf_service import PDFProcessingService
from .statement_parser import StatementParser, mask_account_number
from .storage_service import StorageService
from .vision_service import VisionExtractionService

logger = logging.getLogger(__name__)


class StatementDeleted(Exception):
    """The statement row disappeared while it was being processed."""


def mark_statement_failed(statement_id: int, message: str, session_factory=SessionLocal) -> None:
    with session_factory() as db:
        statement = db.get(BankStatement, statement_id)
        if statement:
            statement.status = ProcessingStatus.FAILED
            statement.error_message = message[:2000]
            statement.processing_completed_at = datetime.utcnow()
            db.commit()


class StatementProcessor:
    """
    Pipeline for one statement:
    1. Render PDF pages to images
    2. Extract each page with the vision model (a few pages in parallel)
    3. Merge and normalize pages
    4. Save results
    """

    def __init__(
        self,
        vision: Optional[VisionExtractionService] = None,
        pdf: Optional[PDFProcessingService] = None,
        storage: Optional[StorageService] = None,
        session_factory=SessionLocal,
    ):
        self.vision = vision or VisionExtractionService()
        self.pdf = pdf or PDFProcessingService()
        self.storage = storage or StorageService()
        self.parser = StatementParser(
            mask_pii=settings.MASK_PII, mask_char=settings.PII_MASK_CHAR, show_last=settings.PII_SHOW_LAST
        )
        self.session_factory = session_factory

    def process(self, statement_id: int) -> bool:
        with self.session_factory() as db:
            statement = db.get(BankStatement, statement_id)
            if not statement:
                logger.error(f"Statement {statement_id} not found")
                return False

            statement.status = ProcessingStatus.PROCESSING
            statement.processing_started_at = datetime.utcnow()
            statement.processing_completed_at = None
            statement.error_message = None
            statement.model_used = self.vision.model
            pdf_path = str(self.storage.absolute_path(statement.filename))
            db.commit()

        image_dir = settings.page_images_path / str(statement_id)
        try:
            image_paths = self.pdf.render_pages(pdf_path, image_dir)
            self._update(statement_id, page_count=len(image_paths))

            pages, logs, errors, usage = self._extract_pages(image_paths)
            if not pages:
                raise RuntimeError(f"No pages could be extracted: {'; '.join(errors.values())}")

            parsed = self.parser.parse_and_merge(pages)
            self._save_results(statement_id, pages, parsed, logs, errors, usage)
            logger.info(f"Statement {statement_id}: {len(parsed['transactions'])} transactions saved")
            return True

        except StatementDeleted:
            logger.info(f"Statement {statement_id} was deleted during processing")
            return False
        except Exception as e:
            logger.exception(f"Statement {statement_id} failed: {e}")
            self.mark_failed(statement_id, str(e) or type(e).__name__)
            return False
        finally:
            self.pdf.cleanup(image_dir)

    def mark_failed(self, statement_id: int, message: str) -> None:
        mark_statement_failed(statement_id, message, self.session_factory)

    def _update(self, statement_id: int, **fields) -> None:
        with self.session_factory() as db:
            statement = db.get(BankStatement, statement_id)
            if not statement:
                raise StatementDeleted()
            for key, value in fields.items():
                setattr(statement, key, value)
            db.commit()

    def _extract_pages(self, image_paths: List[str]):
        page_count = len(image_paths)

        def run(index_path):
            page_number, path = index_path
            started = datetime.utcnow()
            try:
                return page_number, started, self.vision.extract_page(path, page_number, page_count), None
            except Exception as e:
                logger.warning(f"Page {page_number} failed: {e}")
                return page_number, started, None, e

        workers = max(1, min(settings.PAGE_CONCURRENCY, page_count))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(run, enumerate(image_paths, start=1)))

        pages, logs, errors = [], [], {}
        usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}

        for page_number, started, result, error in results:
            log = {'timestamp': started.isoformat(), 'page': page_number, 'action': 'processing_page'}
            if error is not None:
                log.update(status='error', error=str(error))
                errors[f'page_{page_number}'] = str(error)
            else:
                for key in usage:
                    usage[key] += result['usage'].get(key, 0)
                log.update(
                    status='success',
                    tokens_used=result['usage'].get('total_tokens', 0),
                    validated=result['validation_error'] is None,
                    rows=len(result['extraction']['transactions']),
                )
                if result['validation_error']:
                    log['validation_errors'] = result['validation_error']
                    errors[f'page_{page_number}'] = result['validation_error']
                pages.append({**result['extraction'], 'page_number': page_number})
            logs.append(log)

        return pages, logs, errors, usage

    def _save_results(
        self,
        statement_id: int,
        pages: List[Dict[str, Any]],
        parsed: Dict[str, Any],
        logs: List[Dict[str, Any]],
        errors: Dict[str, str],
        usage: Dict[str, int],
    ) -> None:
        with self.session_factory() as db:
            statement = db.get(BankStatement, statement_id)
            if not statement:
                raise StatementDeleted()

            # Reprocessing replaces earlier results
            for model in (Transaction, TransactionSchema, CustomerDetails, BankDetails):
                db.execute(delete(model).where(model.statement_id == statement_id))

            customer = dict(parsed['customer_details'])
            if customer:
                db.add(CustomerDetails(
                    statement_id=statement_id,
                    account_holder_name=customer.pop('account_holder_name', None),
                    account_number=customer.pop('account_number', None),
                    additional_info=customer,
                ))

            bank = dict(parsed['bank_details'])
            if any(v is not None for v in bank.values()):
                db.add(BankDetails(
                    statement_id=statement_id,
                    bank_name=bank.pop('bank_name', None),
                    statement_period_start=bank.pop('statement_period_start', None),
                    statement_period_end=bank.pop('statement_period_end', None),
                    opening_balance=bank.pop('opening_balance', None),
                    closing_balance=bank.pop('closing_balance', None),
                    currency=bank.pop('currency', None),
                    additional_info=bank,
                ))

            schema = parsed['transaction_schema']
            db.add(TransactionSchema(
                statement_id=statement_id,
                columns=schema['columns'],
                column_metadata=schema['column_metadata'],
            ))

            db.add_all(
                Transaction(statement_id=statement_id, **txn) for txn in parsed['transactions']
            )

            failed_pages = [log['page'] for log in logs if log['status'] == 'error']
            statement.raw_extraction_data = [self._mask_raw(page) for page in pages]
            statement.token_usage = usage
            statement.confidence_scores = self._aggregate_confidence(pages)
            statement.processing_logs = logs
            statement.validation_errors = errors or None
            statement.status = ProcessingStatus.COMPLETED
            statement.processing_completed_at = datetime.utcnow()
            statement.error_message = (
                f"Pages {', '.join(map(str, failed_pages))} could not be extracted" if failed_pages else None
            )
            db.commit()

    @staticmethod
    def _mask_raw(page: Dict[str, Any]) -> Dict[str, Any]:
        """Stored raw output must not keep the unmasked account number."""
        if not settings.MASK_PII:
            return page
        customer = dict(page.get('customer_details') or {})
        if customer.get('account_number'):
            customer['account_number'] = mask_account_number(
                customer['account_number'], settings.PII_SHOW_LAST, settings.PII_MASK_CHAR
            )
        return {**page, 'customer_details': customer}

    @staticmethod
    def _aggregate_confidence(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        scores = [p['confidence_scores'] for p in pages if p.get('confidence_scores')]
        if not scores:
            return {}

        keys = ('overall', 'customer_details', 'bank_details', 'transactions')
        return {
            'average': {k: sum(s.get(k, 0) for s in scores) / len(scores) for k in keys},
            'by_page': scores,
            'min_overall': min(s.get('overall', 1.0) for s in scores),
            'max_overall': max(s.get('overall', 0.0) for s in scores),
        }
