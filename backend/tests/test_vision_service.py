import json
from types import SimpleNamespace

import pytest

from app.services.vision_service import ExtractionError, VisionExtractionService, parse_json_object


def test_parse_json_object_plain():
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_json_object_fenced_with_text():
    content = 'Here you go:\n```json\n{"a": {"b": "}"}}\n```\nDone.'
    assert parse_json_object(content) == {"a": {"b": "}"}}


def test_parse_json_object_trailing_text():
    assert parse_json_object('{"a": 1} extra {"b": 2}') == {"a": 1}


@pytest.mark.parametrize("content", ["no json here", '{"a": ', "[1, 2]"])
def test_parse_json_object_errors(content):
    with pytest.raises(ExtractionError):
        parse_json_object(content)


class FakeCompletions:
    def __init__(self, content, finish_reason="stop"):
        self.content = content
        self.finish_reason = finish_reason
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason=self.finish_reason,
                message=SimpleNamespace(content=self.content),
            )],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


def make_service(completions):
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return VisionExtractionService(client=client)


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "page.jpg"
    path.write_bytes(b"\xff\xd8fake")
    return str(path)


def test_extract_page(image):
    body = {
        "customer_details": {"account_holder_name": "Jane", "account_number": "999"},
        "bank_details": {"bank_name": "B", "opening_balance": 10},
        "transaction_columns": ["Date", "Amount"],
        "transactions": [{"Date": "2024-01-01", "Amount": 5}],
        "page_info": {"has_transactions": True},
        "confidence_scores": {"overall": 0.9},
    }
    completions = FakeCompletions(json.dumps(body))
    result = make_service(completions).extract_page(image, 1, 3)

    assert result['validation_error'] is None
    assert result['extraction']['transactions'] == body['transactions']
    assert result['usage']['total_tokens'] == 15
    assert completions.kwargs['response_format'] == {"type": "json_object"}
    assert "Page 1 of 3" in completions.kwargs['messages'][1]['content'][0]['text']


def test_extract_page_truncated(image):
    with pytest.raises(ExtractionError, match="truncated"):
        make_service(FakeCompletions('{"transactions": [', finish_reason="length")).extract_page(image, 1, 1)


def test_extract_page_keeps_rows_on_validation_error(image):
    body = {"transaction_columns": ["Date"], "transactions": [{"Date": "x"}], "confidence_scores": {"overall": "high"}}
    result = make_service(FakeCompletions(json.dumps(body))).extract_page(image, 1, 1)
    assert result['validation_error']
    assert result['extraction']['transactions'] == [{"Date": "x"}]
