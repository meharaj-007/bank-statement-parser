import csv
import io

from app.core.config import settings
from tests.conftest import SAMPLE_PAGES, FakeVision, make_pdf


def upload(client, data=None, name="statement.pdf"):
    return client.post("/api/upload", files={"file": (name, data or make_pdf(), "application/pdf")})


def test_upload_processes_and_serves_statement(client, inline_worker):
    res = upload(client)
    assert res.status_code == 202
    sid = res.json()['statement_id']
    assert res.json()['success'] is True
    assert inline_worker['vision'].calls == [1, 2]

    detail = client.get(f"/api/statements/{sid}").json()
    assert detail['status'] == 'completed'
    assert detail['page_count'] == 2
    assert detail['transaction_count'] == 3
    assert detail['filename'] == 'statement.pdf'
    assert detail['error_message'] is None
    assert detail['customer_details']['account_number'] == 'XXXXXXXX9012'
    assert detail['bank_details']['currency'] == 'BDT'
    assert detail['bank_details']['statement_period_start'] == '2024-01-01'
    assert detail['bank_details']['closing_balance'] == '73500.00'

    listing = client.get("/api/statements").json()
    assert listing['pagination'] == {'page': 1, 'limit': 20, 'total': 1, 'pages': 1}
    item = listing['statements'][0]
    assert item['bank_name'] == 'Example Bank'
    assert item['transaction_count'] == 3
    assert item['period_end'] == '2024-01-31'

    summary = client.get(f"/api/statements/{sid}/summary").json()
    assert summary['total_credit'] == '30000.00'
    assert summary['total_debit'] == '6500.00'
    assert summary['net'] == '23500.00'
    assert (summary['credit_count'], summary['debit_count']) == (1, 2)

    schema = client.get(f"/api/statements/{sid}/schema").json()
    assert schema['columns'][:2] == ['Date', 'Description']

    metadata = client.get(f"/api/statements/{sid}/metadata").json()
    assert metadata['token_usage']['total_tokens'] == 300
    assert metadata['model_used'] == 'fake-vision-model'
    assert metadata['confidence_scores']['average']['overall'] == 0.9
    assert metadata['raw_extraction_data'][0]['customer_details']['account_number'] == 'XXXXXXXX9012'
    assert [log['status'] for log in metadata['processing_logs']] == ['success', 'success']

    pdf = client.get(f"/api/statements/{sid}/file")
    assert pdf.status_code == 200
    assert pdf.headers['content-type'] == 'application/pdf'
    assert pdf.headers['content-disposition'].startswith('inline')

    rows = list(csv.reader(io.StringIO(client.get(f"/api/statements/{sid}/csv").text)))
    assert ['Date', 'Description', 'Withdrawal', 'Deposit', 'Balance', 'Parsed Date', 'Parsed Amount', 'Type', 'Page'] in rows


def test_page_images_are_cleaned_up(client, inline_worker):
    upload(client)
    assert list(settings.page_images_path.iterdir()) == []


def test_transaction_filters(client, inline_worker):
    sid = upload(client).json()['statement_id']
    url = f"/api/statements/{sid}/transactions"

    all_rows = client.get(url).json()
    assert [t['data']['Description'] for t in all_rows['transactions']] == [
        'ATM Cash Withdrawal', 'বেতন Salary Credit', 'Card Payment',
    ]
    assert all_rows['summary'] == {'total_credit': '30000.00', 'total_debit': '6500.00', 'net': '23500.00'}

    debits = client.get(url, params={'type': 'debit', 'sort_by': 'amount', 'sort_order': 'desc'}).json()
    assert [t['amount'] for t in debits['transactions']] == ['5000.00', '1500.00']
    assert debits['summary']['total_credit'] == '0.00'

    # Non-ASCII search works because JSON is stored unescaped
    found = client.get(url, params={'search': 'বেতন'}).json()
    assert found['pagination']['total'] == 1

    ranged = client.get(url, params={'date_from': '2024-01-10', 'min_amount': 1000}).json()
    assert [t['transaction_date'] for t in ranged['transactions']] == ['2024-01-15', '2024-01-20']

    paged = client.get(url, params={'limit': 2, 'page': 2}).json()
    assert paged['pagination'] == {'page': 2, 'limit': 2, 'total': 3, 'pages': 2}
    assert len(paged['transactions']) == 1

    assert client.get(url, params={'type': 'bogus'}).status_code == 422

    everywhere = client.get("/api/transactions", params={'statement_ids': str(sid), 'search': 'atm'}).json()
    assert everywhere['pagination']['total'] == 1
    assert client.get("/api/transactions", params={'statement_ids': 'a,b'}).status_code == 400


def test_duplicate_upload_rejected(client, inline_worker):
    data = make_pdf()
    first = upload(client, data).json()['statement_id']
    res = upload(client, data, name="again.pdf")
    assert res.status_code == 409
    assert res.json() == {'error': True, 'message': 'This file has already been uploaded', 'existing_statement_id': first}


def test_failed_statement_reprocessed_on_reupload(client, inline_worker):
    inline_worker['vision'] = FakeVision([RuntimeError("model down"), RuntimeError("model down")])
    data = make_pdf()
    sid = upload(client, data).json()['statement_id']

    failed = client.get(f"/api/statements/{sid}").json()
    assert failed['status'] == 'failed'
    assert 'model down' in failed['error_message']

    inline_worker['vision'] = FakeVision(SAMPLE_PAGES)
    res = upload(client, data)
    assert res.status_code == 202
    assert res.json()['statement_id'] == sid
    assert client.get(f"/api/statements/{sid}").json()['status'] == 'completed'


def test_partial_page_failure_completes_with_note(client, inline_worker):
    inline_worker['vision'] = FakeVision([SAMPLE_PAGES[0], RuntimeError("timeout")])
    sid = upload(client).json()['statement_id']

    detail = client.get(f"/api/statements/{sid}").json()
    assert detail['status'] == 'completed'
    assert detail['transaction_count'] == 2
    assert detail['error_message'] == 'Pages 2 could not be extracted'


def test_reprocess_replaces_results(client, inline_worker):
    sid = upload(client).json()['statement_id']
    assert client.post(f"/api/statements/{sid}/reprocess").status_code == 202
    assert client.get(f"/api/statements/{sid}").json()['transaction_count'] == 3


def test_upload_validation(client, inline_worker):
    assert upload(client, b"not a pdf").status_code == 400
    assert upload(client, name="notes.txt").json()['message'] == 'Only PDF files are allowed'
    assert inline_worker['queued'] == []


def test_upload_filename_is_not_used_for_paths(client, inline_worker):
    sid = upload(client, name="../../../etc/evil.pdf").json()['statement_id']
    detail = client.get(f"/api/statements/{sid}").json()
    assert detail['filename'] == 'evil.pdf'
    assert not any(p.name == 'evil.pdf' for p in settings.upload_path.rglob('*'))


def test_upload_size_limit(client, inline_worker, monkeypatch):
    monkeypatch.setattr(settings, 'MAX_UPLOAD_SIZE', 100)
    res = upload(client)
    assert res.status_code == 413
    assert not [p for p in settings.upload_path.rglob('*') if p.is_file()]


def test_queue_unavailable_marks_failed(client, monkeypatch):
    from app.worker import process_statement_task

    def broken(*_, **__):
        raise ConnectionError("redis down")

    monkeypatch.setattr(process_statement_task, "apply_async", broken)
    res = upload(client)
    assert res.status_code == 503
    sid = res.json()['statement_id']
    assert client.get(f"/api/statements/{sid}").json()['status'] == 'failed'


def test_schema_update(client, inline_worker):
    sid = upload(client).json()['statement_id']
    url = f"/api/statements/{sid}/schema"

    res = client.put(url, json={'column_metadata': {'Balance': {'type': 'number', 'display_name': 'Bal'}}})
    assert res.status_code == 200
    assert res.json()['schema']['column_metadata']['Balance'] == {'type': 'number', 'display_name': 'Bal'}
    # Other columns untouched
    assert res.json()['schema']['column_metadata']['Date']['type'] == 'date'

    assert client.put(url, json={'column_metadata': {'Balance': {'type': 'money', 'display_name': 'x'}}}).status_code == 422
    assert client.put(url, json={'column_metadata': {'Nope': {'type': 'text', 'display_name': 'x'}}}).status_code == 400


def test_list_filters_and_search(client, inline_worker):
    upload(client, make_pdf(text="one"), name="january.pdf")
    upload(client, make_pdf(text="two"), name="february.pdf")

    assert client.get("/api/statements", params={'search': 'janu'}).json()['pagination']['total'] == 1
    assert client.get("/api/statements", params={'search': '9012'}).json()['pagination']['total'] == 2
    assert client.get("/api/statements", params={'status': 'failed'}).json()['statements'] == []
    assert client.get("/api/statements", params={'status': 'nope'}).status_code == 422


def test_delete_statement(client, inline_worker):
    sid = upload(client).json()['statement_id']
    assert client.delete(f"/api/statements/{sid}").json()['success'] is True
    assert client.get(f"/api/statements/{sid}").status_code == 404
    assert client.get(f"/api/statements/{sid}/transactions").json()['message'] == 'Statement not found'
    assert not [p for p in settings.upload_path.rglob('*.pdf')]


def test_statement_deleted_during_processing(client, inline_worker):
    class DeletingVision(FakeVision):
        def extract_page(self, image_path, page_number, page_count):
            if page_number == 1:
                client.delete("/api/statements/1")
            return super().extract_page(image_path, page_number, page_count)

    inline_worker['vision'] = DeletingVision(SAMPLE_PAGES)
    assert upload(client).status_code == 202
    assert client.get("/api/statements").json()['pagination']['total'] == 0
