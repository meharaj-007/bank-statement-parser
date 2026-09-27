from datetime import date
from decimal import Decimal

import pytest

from app.services.statement_parser import (
    StatementParser,
    classify_column,
    mask_account_number,
    normalize_currency,
    parse_amount,
    parse_date,
)
from tests.conftest import COLUMNS, SAMPLE_PAGES, page


@pytest.mark.parametrize("value, expected", [
    ("1,234.56", (Decimal("1234.56"), None)),
    ("(100.00)", (Decimal("-100.00"), None)),
    ("-250", (Decimal("-250"), None)),
    ("500.00 Dr", (Decimal("500.00"), "debit")),
    ("1,000.00 CR", (Decimal("1000.00"), "credit")),
    ("Tk. 1,000", (Decimal("1000"), None)),
    ("1.234,56", (Decimal("1234.56"), None)),
    (12.5, (Decimal("12.5"), None)),
    ("-", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
    ("n/a", (None, None)),
])
def test_parse_amount(value, expected):
    assert parse_amount(value) == expected


@pytest.mark.parametrize("value, default, expected", [
    ("2024-01-05", None, date(2024, 1, 5)),  # dateutil dayfirst would give May 1
    ("2024/01/05", None, date(2024, 1, 5)),
    ("05/01/2024", None, date(2024, 1, 5)),
    ("01-Feb-2024", None, date(2024, 2, 1)),
    ("20 Dec", date(2023, 12, 1), date(2023, 12, 20)),
    ("05 Jan", date(2023, 12, 1), date(2024, 1, 5)),  # Dec -> Jan rollover
    ("05-Jan-2023", date(2023, 12, 1), date(2023, 1, 5)),  # Explicit year is kept
    ("not a date", None, None),
])
def test_parse_date(value, default, expected):
    assert parse_date(value, default=default) == expected


@pytest.mark.parametrize("column, role", [
    ("Description", "description"),  # Contains "cr" but is not a credit column
    ("Transaction Details", "description"),
    ("Withdrawals", "debit"),
    ("Paid Out", "debit"),
    ("Deposits", "credit"),
    ("Credit", "credit"),
    ("Dr/Cr", "indicator"),
    ("Balance", "balance"),
    ("Value Date", "date"),
    ("Amount", "amount"),
    ("Cheque No", None),
])
def test_classify_column(column, role):
    assert classify_column(column) == role


def test_normalize_currency():
    assert normalize_currency("Taka") == "BDT"
    assert normalize_currency("৳") == "BDT"
    assert normalize_currency("US Dollar") == "USD"
    assert normalize_currency("usd") == "USD"
    assert normalize_currency("Currency: EUR") == "EUR"
    assert normalize_currency(None) is None
    assert normalize_currency("doubloons") is None


def test_mask_account_number():
    assert mask_account_number("1234-5678-9012") == "XXXXXXXX9012"
    assert mask_account_number("123") == "XX3"
    assert mask_account_number(None) is None


def test_merge_pages():
    parsed = StatementParser().parse_and_merge(
        [{**p, 'page_number': i} for i, p in enumerate(SAMPLE_PAGES, start=1)]
    )

    assert parsed['customer_details']['account_number'] == "XXXXXXXX9012"
    bank = parsed['bank_details']
    assert bank['currency'] == "BDT"
    assert bank['statement_period_start'] == date(2024, 1, 1)
    assert bank['opening_balance'] == Decimal("50000.0")
    assert bank['closing_balance'] == Decimal("73500.0")  # From the last page

    assert parsed['transaction_schema']['columns'] == COLUMNS
    meta = parsed['transaction_schema']['column_metadata']
    assert meta['Date']['type'] == 'date'
    assert meta['Description']['type'] == 'text'
    assert meta['Withdrawal']['type'] == 'currency'

    txns = parsed['transactions']
    assert len(txns) == 3  # Page 2's repeated first row dropped
    assert [t['row_index'] for t in txns] == [0, 1, 2]
    assert [(t['transaction_type'], t['amount']) for t in txns] == [
        ('debit', Decimal("5000.0")),
        ('credit', Decimal("30000.0")),
        ('debit', Decimal("1500.00")),
    ]
    assert txns[2]['balance'] == Decimal("73500.00")
    assert txns[2]['page_number'] == 2
    assert txns[0]['transaction_date'] == date(2024, 1, 1)


def test_identical_rows_on_same_page_are_kept():
    row = {"Date": "02-Jan-2024", "Description": "ATM", "Withdrawal": 100, "Deposit": None, "Balance": None}
    parsed = StatementParser().parse_and_merge([{**page(columns=COLUMNS, rows=[row, row]), 'page_number': 1}])
    assert len(parsed['transactions']) == 2


def test_amount_with_indicator_column():
    columns = ["Txn Date", "Particulars", "Amount", "Dr/Cr", "Balance"]
    rows = [
        {"Txn Date": "03/02/2024", "Particulars": "Transfer", "Amount": 200, "Dr/Cr": "Dr", "Balance": 800},
        {"Txn Date": "04/02/2024", "Particulars": "Refund", "Amount": 50, "Dr/Cr": "Cr", "Balance": 850},
        {"Txn Date": "05/02/2024", "Particulars": "Fee", "Amount": -5, "Dr/Cr": None, "Balance": 845},
    ]
    parsed = StatementParser().parse_and_merge([{**page(columns=columns, rows=rows), 'page_number': 1}])
    assert [(t['transaction_type'], t['amount']) for t in parsed['transactions']] == [
        ('debit', Decimal("200")), ('credit', Decimal("50")), ('debit', Decimal("5")),
    ]
    assert parsed['transactions'][0]['transaction_date'] == date(2024, 2, 3)


def test_year_less_dates_use_period():
    columns = ["Date", "Description", "Debit", "Credit"]
    rows = [
        {"Date": "28 Dec", "Description": "A", "Debit": 1, "Credit": None},
        {"Date": "02 Jan", "Description": "B", "Debit": None, "Credit": 2},
    ]
    bank = {'statement_period_start': '2023-12-15', 'statement_period_end': '2024-01-14'}
    parsed = StatementParser().parse_and_merge([{**page(bank=bank, columns=columns, rows=rows), 'page_number': 1}])
    assert [t['transaction_date'] for t in parsed['transactions']] == [date(2023, 12, 28), date(2024, 1, 2)]


def test_masking_can_be_disabled():
    pages = [{**SAMPLE_PAGES[0], 'page_number': 1}]
    parsed = StatementParser(mask_pii=False).parse_and_merge(pages)
    assert parsed['customer_details']['account_number'] == "1234-5678-9012"
