import base64
import json
import logging
import re
from typing import Any, Dict, List, Optional

from groq import Groq
from pydantic import BaseModel, ValidationError

from ..core.config import settings

logger = logging.getLogger(__name__)


class CustomerDetailsExtraction(BaseModel):
    account_holder_name: Optional[str] = None
    account_number: Optional[str] = None


class BankDetailsExtraction(BaseModel):
    bank_name: Optional[str] = None
    statement_period_start: Optional[str] = None
    statement_period_end: Optional[str] = None
    opening_balance: Optional[Any] = None
    closing_balance: Optional[Any] = None
    currency: Optional[str] = None


class PageInfo(BaseModel):
    appears_to_be_first_page: bool = False
    appears_to_be_last_page: bool = False
    has_header_info: bool = False
    has_transactions: bool = False


class PageExtraction(BaseModel):
    customer_details: CustomerDetailsExtraction = CustomerDetailsExtraction()
    bank_details: BankDetailsExtraction = BankDetailsExtraction()
    transaction_columns: List[str] = []
    transactions: List[Dict[str, Any]] = []
    page_info: PageInfo = PageInfo()
    confidence_scores: Optional[Dict[str, float]] = None


class ExtractionError(Exception):
    """The model response for a page could not be used."""


SYSTEM_PROMPT = """You are an expert financial document analysis assistant specialized in bank statement data extraction.

- Extract data exactly as printed, preserving column names and structure
- Handle statement layouts from any bank or country
- Return only a single valid JSON object, no markdown or commentary
- Use null for unclear, missing or unreadable values. Never guess."""

EXTRACTION_PROMPT = """Extract all data from this bank statement page into this JSON structure:

{
    "customer_details": {
        "account_holder_name": "string or null",
        "account_number": "string or null"
    },
    "bank_details": {
        "bank_name": "string or null",
        "statement_period_start": "YYYY-MM-DD or null",
        "statement_period_end": "YYYY-MM-DD or null",
        "opening_balance": number or null,
        "closing_balance": number or null,
        "currency": "currency as written (e.g. 'Taka', 'BDT', '৳', 'USD') or null"
    },
    "transaction_columns": ["exact", "column", "headers"],
    "transactions": [
        {"ColumnName1": "value", "ColumnName2": 123.45, "ColumnName3": null}
    ],
    "page_info": {
        "appears_to_be_first_page": boolean,
        "appears_to_be_last_page": boolean,
        "has_header_info": boolean,
        "has_transactions": boolean
    },
    "confidence_scores": {
        "overall": 0.0-1.0,
        "customer_details": 0.0-1.0,
        "bank_details": 0.0-1.0,
        "transactions": 0.0-1.0
    }
}

RULES:
1. transaction_columns: the EXACT headers of the transaction table, same case and spacing
   (e.g. ["Date", "Particulars", "Withdrawals", "Deposits", "Balance"]). If this page has no
   header row but continues a table, repeat the headers from the table's layout.
2. transactions: one object per row, keys taken from transaction_columns.
   - Extract EVERY visible row on this page, in printed order
   - Amounts as plain numbers (no thousands separators or currency symbols), null for empty cells
   - Keep full description/narration text
   - Keep transaction date strings exactly as printed
   - Keep Dr/Cr or +/- indicators if the statement shows them
   - Do not include page totals, "balance carried forward" or column-header rows as transactions
3. Header fields (customer_details, bank_details) only from what is visible on THIS page; null otherwise.
4. statement_period_start / statement_period_end: from labels like "Statement Period", "From", "To",
   converted to YYYY-MM-DD. If only one statement date is shown, use it for both.
5. currency: return exactly the currency text or symbol you see; do not convert it.
6. confidence_scores: your confidence in each part of this page's extraction."""


def parse_json_object(content: str) -> Dict[str, Any]:
    """Parse the first JSON object in a model response, tolerating code fences or surrounding text."""
    text = content.strip()
    fenced = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    start = text.find('{')
    if start < 0:
        raise ExtractionError("Response contains no JSON object")

    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise ExtractionError(f"Response is not valid JSON: {e}") from e

    if not isinstance(obj, dict):
        raise ExtractionError("Response JSON is not an object")
    return obj


class VisionExtractionService:
    """Sends one page image to a Groq vision model and returns the structured extraction."""

    def __init__(self, client: Optional[Groq] = None):
        if client is None:
            if not settings.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY is required")
            client = Groq(
                api_key=settings.GROQ_API_KEY,
                timeout=settings.GROQ_REQUEST_TIMEOUT,
                max_retries=settings.GROQ_MAX_RETRIES,  # SDK backs off on 429 / 5xx
            )
        self.client = client
        self.model = settings.GROQ_MODEL

    def extract_page(self, image_path: str, page_number: int, page_count: int) -> Dict[str, Any]:
        """
        Returns:
            {
                'extraction': dict,          # PageExtraction fields
                'validation_error': str|None,
                'usage': {'prompt_tokens', 'completion_tokens', 'total_tokens'},
            }

        Raises:
            ExtractionError: the response was truncated or unparseable
        """
        with open(image_path, 'rb') as f:
            image_b64 = base64.b64encode(f.read()).decode('ascii')

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Page {page_number} of {page_count} of a bank statement.\n\n{EXTRACTION_PROMPT}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    ],
                },
            ],
            temperature=settings.GROQ_TEMPERATURE,
            max_tokens=settings.GROQ_MAX_TOKENS,
            response_format={"type": "json_object"},
        )

        usage = {
            'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
            'completion_tokens': response.usage.completion_tokens if response.usage else 0,
            'total_tokens': response.usage.total_tokens if response.usage else 0,
        }
        choice = response.choices[0]

        if choice.finish_reason == 'length':
            raise ExtractionError(
                f"Response truncated at {settings.GROQ_MAX_TOKENS} tokens; raise GROQ_MAX_TOKENS or lower PDF_DPI"
            )

        raw = parse_json_object(choice.message.content or '')

        validation_error = None
        try:
            extraction = PageExtraction.model_validate(raw).model_dump()
        except ValidationError as e:
            # Keep what we can: rows and columns are what matter most
            logger.warning(f"Page {page_number}: validation errors: {e}")
            validation_error = str(e)
            extraction = {
                'customer_details': raw.get('customer_details') if isinstance(raw.get('customer_details'), dict) else {},
                'bank_details': raw.get('bank_details') if isinstance(raw.get('bank_details'), dict) else {},
                'transaction_columns': [c for c in raw.get('transaction_columns') or [] if isinstance(c, str)],
                'transactions': [t for t in raw.get('transactions') or [] if isinstance(t, dict)],
                'page_info': raw.get('page_info') if isinstance(raw.get('page_info'), dict) else {},
                'confidence_scores': raw.get('confidence_scores') if isinstance(raw.get('confidence_scores'), dict) else None,
            }

        logger.info(
            f"Page {page_number}: {len(extraction['transactions'])} rows, {usage['total_tokens']} tokens"
        )
        return {'extraction': extraction, 'validation_error': validation_error, 'usage': usage}
