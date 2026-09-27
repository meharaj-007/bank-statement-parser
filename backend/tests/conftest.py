import os
import shutil
import tempfile
from pathlib import Path

# Settings are read at import time, so point everything at a temp dir first
_TMP = Path(tempfile.mkdtemp(prefix="bsp-tests-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "UPLOAD_DIR": str(_TMP / "uploads"),
    "PAGE_IMAGES_DIR": str(_TMP / "page_images"),
    "LOG_DIR": str(_TMP / "logs"),
    "GROQ_API_KEY": "test-key",
    "CELERY_BROKER_URL": "memory://",
    "MASK_PII": "true",
})

import fitz  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.services.statement_processor import StatementProcessor  # noqa: E402
from app.worker import process_statement_task  # noqa: E402
from main import app  # noqa: E402


class FakeVision:
    """Stands in for VisionExtractionService, returning canned page extractions."""

    model = "fake-vision-model"

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def extract_page(self, image_path, page_number, page_count):
        self.calls.append(page_number)
        page = self.pages[page_number - 1]
        if isinstance(page, Exception):
            raise page
        return {
            'extraction': page,
            'validation_error': None,
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
        }


def page(customer=None, bank=None, columns=None, rows=None, confidence=0.9):
    return {
        'customer_details': customer or {'account_holder_name': None, 'account_number': None},
        'bank_details': bank or {},
        'transaction_columns': columns or [],
        'transactions': rows or [],
        'page_info': {},
        'confidence_scores': {'overall': confidence, 'customer_details': confidence,
                              'bank_details': confidence, 'transactions': confidence},
    }


COLUMNS = ["Date", "Description", "Withdrawal", "Deposit", "Balance"]

SAMPLE_PAGES = [
    page(
        customer={'account_holder_name': 'Abdul Karim', 'account_number': '1234-5678-9012'},
        bank={'bank_name': 'Example Bank', 'statement_period_start': '2024-01-01',
              'statement_period_end': '2024-01-31', 'opening_balance': 50000.0,
              'closing_balance': None, 'currency': 'Taka'},
        columns=COLUMNS,
        rows=[
            {"Date": "01-Jan-2024", "Description": "ATM Cash Withdrawal", "Withdrawal": 5000.0, "Deposit": None, "Balance": 45000.0},
            {"Date": "15-Jan-2024", "Description": "বেতন Salary Credit", "Withdrawal": None, "Deposit": 30000.0, "Balance": 75000.0},
        ],
    ),
    page(
        bank={'closing_balance': 73500.0},
        columns=COLUMNS,
        rows=[
            # Repeated from the bottom of page 1
            {"Date": "15-Jan-2024", "Description": "বেতন Salary Credit", "Withdrawal": None, "Deposit": 30000.0, "Balance": 75000.0},
            {"Date": "20-Jan-2024", "Description": "Card Payment", "Withdrawal": "1,500.00", "Deposit": None, "Balance": "73,500.00"},
        ],
    ),
]


def make_pdf(pages: int = 2, text: str = "Statement") -> bytes:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{text} page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
    for folder in ("uploads", "page_images"):
        shutil.rmtree(_TMP / folder, ignore_errors=True)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def inline_worker(monkeypatch):
    """Run queued statements immediately with a fake vision model."""
    state = {'vision': FakeVision(SAMPLE_PAGES), 'queued': []}

    def apply_async(args, **_):
        state['queued'].append(args[0])
        StatementProcessor(vision=state['vision']).process(args[0])

    monkeypatch.setattr(process_statement_task, "apply_async", apply_async)
    return state
