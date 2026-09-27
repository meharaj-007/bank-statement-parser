import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as date_parser

logger = logging.getLogger(__name__)


# Currency name/symbol to ISO 4217 code
CURRENCY_MAPPING = {
    'taka': 'BDT', 'bangladesh taka': 'BDT', 'bangladeshi taka': 'BDT', 'tk': 'BDT', '৳': 'BDT',
    'dollar': 'USD', 'us dollar': 'USD', '$': 'USD',
    'euro': 'EUR', '€': 'EUR',
    'pound': 'GBP', 'pound sterling': 'GBP', '£': 'GBP',
    'rupee': 'INR', 'indian rupee': 'INR', '₹': 'INR',
    'yen': 'JPY', 'japanese yen': 'JPY', '¥': 'JPY',
    'yuan': 'CNY', 'chinese yuan': 'CNY', 'renminbi': 'CNY',
    'riyal': 'SAR', 'saudi riyal': 'SAR',
    'dirham': 'AED', 'uae dirham': 'AED',
    'ringgit': 'MYR', 'malaysian ringgit': 'MYR',
    'baht': 'THB', 'thai baht': 'THB',
    'won': 'KRW', 'south korean won': 'KRW',
    'franc': 'CHF', 'swiss franc': 'CHF',
    'rand': 'ZAR', 'south african rand': 'ZAR',
}

DEBIT_WORDS = {'debit', 'debits', 'dr', 'withdrawal', 'withdrawals', 'withdraw', 'payment', 'payments'}
CREDIT_WORDS = {'credit', 'credits', 'cr', 'deposit', 'deposits', 'lodgement', 'lodgements', 'receipt', 'receipts'}
DEBIT_PHRASES = ('paid out', 'money out')
CREDIT_PHRASES = ('paid in', 'money in')
DESCRIPTION_WORDS = {'description', 'details', 'narration', 'particulars', 'remarks', 'transaction'}

ISO_LIKE_DATE = re.compile(r'^\s*\d{4}[-/.]\d{1,2}[-/.]\d{1,2}')


def normalize_currency(currency_str: Optional[str]) -> Optional[str]:
    """Map a currency name, symbol or code to its ISO 4217 code. Returns None if unknown."""
    if not currency_str:
        return None

    cleaned = re.sub(r'\b(currency|code)\b', '', str(currency_str).strip().lower()).strip(' :')
    if not cleaned:
        return None

    if re.fullmatch(r'[a-z]{3}', cleaned):
        return cleaned.upper()

    if cleaned in CURRENCY_MAPPING:
        return CURRENCY_MAPPING[cleaned]

    # Longest key first so 'us dollar' wins over 'dollar'
    for key in sorted(CURRENCY_MAPPING, key=len, reverse=True):
        if key in cleaned:
            return CURRENCY_MAPPING[key]

    logger.warning(f"Currency '{currency_str}' not recognized")
    return None


def mask_account_number(value: Optional[str], show_last: int = 4, mask_char: str = 'X') -> Optional[str]:
    """Mask all but the last `show_last` alphanumeric characters of an account number."""
    if not value:
        return value
    cleaned = re.sub(r'[^0-9A-Za-z]', '', str(value))
    if not cleaned:
        return value
    if len(cleaned) <= show_last:
        return mask_char * (len(cleaned) - 1) + cleaned[-1]
    return mask_char * (len(cleaned) - show_last) + cleaned[-show_last:]


def _words(column: str) -> set:
    return set(re.findall(r'[a-z]+', column.lower()))


def classify_column(column: str) -> Optional[str]:
    """Return 'date', 'balance', 'indicator', 'debit', 'credit', 'amount', 'description' or None."""
    words = _words(column)
    lowered = column.lower()

    if 'date' in words:
        return 'date'
    if 'balance' in words:
        return 'balance'

    is_debit = bool(words & DEBIT_WORDS) or any(p in lowered for p in DEBIT_PHRASES)
    is_credit = bool(words & CREDIT_WORDS) or any(p in lowered for p in CREDIT_PHRASES)

    if is_debit and is_credit:
        # e.g. "Dr/Cr" holds the direction of a single amount column
        return 'amount' if 'amount' in words else 'indicator'
    if is_debit:
        return 'debit'
    if is_credit:
        return 'credit'
    if 'amount' in words:
        return 'amount'
    if words & DESCRIPTION_WORDS:
        return 'description'
    return None


def parse_amount(value: Any) -> Tuple[Optional[Decimal], Optional[str]]:
    """
    Parse an amount cell.

    Returns (amount, direction) where direction is 'debit'/'credit' when the cell
    itself carries a Dr/Cr marker, otherwise None. Amount keeps its sign.
    """
    if value is None or isinstance(value, bool):
        return None, None

    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value)), None
        except InvalidOperation:
            return None, None

    if not isinstance(value, str):
        return None, None

    text = value.strip()
    if not text or text in {'-', '–', '—'}:
        return None, None

    direction = None
    marker = re.search(r'\b(dr|cr)\.?\s*$', text, re.IGNORECASE)
    if marker:
        direction = 'debit' if marker.group(1).lower() == 'dr' else 'credit'

    negative = (
        bool(re.search(r'(^|[^\d])-\s*[\d.,]', text))
        or (text.startswith('(') and text.endswith(')'))
        or text.endswith('-')
    )
    digits = re.sub(r'[^\d.,]', '', text).strip('.,')
    if not re.search(r'\d', digits):
        return None, None

    # "1.234,56" style: comma is the decimal separator
    if ',' in digits and '.' in digits and digits.rfind(',') > digits.rfind('.'):
        digits = digits.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d+,\d{2}', digits):
        digits = digits.replace(',', '.')
    else:
        digits = digits.replace(',', '')

    try:
        amount = Decimal(digits)
    except InvalidOperation:
        return None, None

    return (-amount if negative else amount), direction


def parse_date(value: Any, default: Optional[date] = None) -> Optional[date]:
    """
    Parse a date cell.

    ISO-like values (YYYY-MM-DD) are read year-first; everything else day-first,
    which matches most non-US statements. `default` supplies the year when the
    cell has none (e.g. "05 Jan").
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value or not isinstance(value, str):
        return None

    text = value.strip()
    try:
        if ISO_LIKE_DATE.match(text):
            return date_parser.parse(text, yearfirst=True, dayfirst=False).date()

        if not default:
            return date_parser.parse(text, dayfirst=True).date()

        parsed = date_parser.parse(text, dayfirst=True, default=datetime(default.year, default.month, 1)).date()

        # Parsing with a different default year tells us whether the cell had its own year
        probe = date_parser.parse(text, dayfirst=True, default=datetime(default.year + 4, 1, 1)).date()
        year_missing = probe.year != parsed.year

        # Year came from the period start; roll over for Dec -> Jan statements
        if year_missing and parsed < default:
            parsed = parsed.replace(year=parsed.year + 1)
        return parsed
    except (ValueError, TypeError, OverflowError):
        return None


class StatementParser:
    """Merges per-page LLM extractions into one normalized statement."""

    BOUNDARY_ROWS = 5  # Rows compared when dropping repeats across a page break

    def __init__(self, mask_pii: bool = True, mask_char: str = 'X', show_last: int = 4):
        self.mask_pii = mask_pii
        self.mask_char = mask_char
        self.show_last = show_last

    def parse_and_merge(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Args:
            pages: Per-page extraction dicts, in page order. Each must carry
                   `page_number`.
        """
        if not pages:
            raise ValueError("No pages to parse")

        customer_details = self._merge_customer_details(pages)
        bank_details = self._merge_bank_details(pages)
        schema = self._detect_schema(pages)
        roles = {col: classify_column(col) for col in schema['columns']}

        period_start = bank_details.get('statement_period_start')
        transactions = []
        previous_tail: List[str] = []
        row_index = 0

        for page in pages:
            page_rows = [row for row in page.get('transactions') or [] if isinstance(row, dict)]
            signatures = [self._signature(row) for row in page_rows]

            # Drop leading rows repeated from the end of the previous page
            skip = 0
            while skip < len(page_rows) and signatures[skip] in previous_tail:
                skip += 1
            if skip:
                logger.info(f"Page {page['page_number']}: dropped {skip} rows repeated from previous page")

            for row in page_rows[skip:]:
                transactions.append(self._normalize_transaction(row, roles, page['page_number'], row_index, period_start))
                row_index += 1

            if signatures:
                previous_tail = signatures[-self.BOUNDARY_ROWS:]

        return {
            'customer_details': customer_details,
            'bank_details': bank_details,
            'transaction_schema': schema,
            'transactions': transactions,
        }

    @staticmethod
    def _signature(row: Dict[str, Any]) -> str:
        return json.dumps(row, sort_keys=True, default=str)

    def _merge_customer_details(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Take customer details from the first page that has them."""
        for page in pages:
            customer = dict(page.get('customer_details') or {})
            if customer.get('account_holder_name') or customer.get('account_number'):
                if self.mask_pii and customer.get('account_number'):
                    customer['account_number'] = mask_account_number(
                        customer['account_number'], self.show_last, self.mask_char
                    )
                return customer
        return {}

    def _merge_bank_details(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """First non-null value per field, except closing balance which comes from the last page."""
        merged: Dict[str, Any] = {}
        for page in pages:
            for key, value in (page.get('bank_details') or {}).items():
                if value is None:
                    continue
                if key == 'closing_balance' or merged.get(key) is None:
                    merged[key] = value

        merged['currency'] = normalize_currency(merged.get('currency'))
        for key in ('statement_period_start', 'statement_period_end'):
            merged[key] = parse_date(merged.get(key))
        for key in ('opening_balance', 'closing_balance'):
            merged[key] = parse_amount(merged.get(key))[0]
        return merged

    def _detect_schema(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Union of transaction columns across pages, in first-seen order, with inferred types."""
        columns: List[str] = []
        for page in pages:
            for col in page.get('transaction_columns') or []:
                if isinstance(col, str) and col not in columns:
                    columns.append(col)
            # Keys used in rows but missing from the header list
            for row in page.get('transactions') or []:
                if isinstance(row, dict):
                    for col in row:
                        if col not in columns:
                            columns.append(col)

        samples = [row for page in pages for row in (page.get('transactions') or [])[:10] if isinstance(row, dict)]
        column_metadata = {
            col: {'type': self._infer_column_type(col, [row.get(col) for row in samples]), 'display_name': col}
            for col in columns
        }
        return {'columns': columns, 'column_metadata': column_metadata}

    def _normalize_transaction(
        self,
        row: Dict[str, Any],
        roles: Dict[str, Optional[str]],
        page_number: int,
        row_index: int,
        period_start: Optional[date],
    ) -> Dict[str, Any]:
        amount, txn_type = self._extract_amount_and_type(row, roles)
        balance_col = next((c for c, r in roles.items() if r == 'balance'), None)

        return {
            'data': row,
            'transaction_date': self._extract_date(row, roles, period_start),
            'amount': amount,
            'transaction_type': txn_type,
            'balance': parse_amount(row.get(balance_col))[0] if balance_col else None,
            'page_number': page_number,
            'row_index': row_index,
        }

    @staticmethod
    def _extract_date(row: Dict[str, Any], roles: Dict[str, Optional[str]], period_start: Optional[date]) -> Optional[date]:
        date_cols = [c for c, r in roles.items() if r == 'date']
        # Prefer the posting/transaction date over the value date
        date_cols.sort(key=lambda c: 'value' in c.lower())
        candidates = date_cols or list(roles)[:1]

        for col in candidates:
            parsed = parse_date(row.get(col), default=period_start)
            if parsed:
                return parsed
        return None

    @staticmethod
    def _extract_amount_and_type(row: Dict[str, Any], roles: Dict[str, Optional[str]]) -> Tuple[Optional[Decimal], Optional[str]]:
        """
        Strategies, in order:
        1. Separate debit / credit (withdrawal / deposit) columns
        2. Single amount column, direction from a Dr/Cr column, a Dr/Cr suffix, or the sign
        """
        for role in ('debit', 'credit'):
            for col in (c for c, r in roles.items() if r == role):
                value, _ = parse_amount(row.get(col))
                if value:
                    return abs(value), role

        indicator_col = next((c for c, r in roles.items() if r == 'indicator'), None)
        for col in (c for c, r in roles.items() if r == 'amount'):
            value, direction = parse_amount(row.get(col))
            if value is None:
                continue

            if indicator_col:
                marker = str(row.get(indicator_col) or '').strip().lower()
                if marker.startswith('d'):
                    direction = 'debit'
                elif marker.startswith('c'):
                    direction = 'credit'

            if direction is None:
                direction = 'debit' if value < 0 else 'credit'
            return abs(value), direction

        return None, None

    @staticmethod
    def _infer_column_type(column: str, sample_values: List[Any]) -> str:
        """Returns 'date', 'currency', 'number' or 'text'."""
        role = classify_column(column)
        if role == 'date':
            return 'date'
        if role in ('debit', 'credit', 'amount', 'balance'):
            return 'currency'
        if role in ('description', 'indicator'):
            return 'text'

        present = [v for v in sample_values if v not in (None, '')]
        if present and sum(parse_amount(v)[0] is not None for v in present) > len(present) * 0.5:
            return 'number'
        return 'text'
