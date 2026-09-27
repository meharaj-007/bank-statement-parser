# Bank Statement Parser

Extracts transactions from PDF bank statements using Groq vision models. Each page is rendered to an image and read by the model, then pages are merged, normalized and stored. Works with any column layout: the original column names are kept and a schema is detected per statement.

## Features

- **Per-page vision extraction** with Groq, several pages in parallel
- **Any layout**: Debit/Credit, Withdrawal/Deposit, signed Amount, Amount + Dr/Cr column, Dr/Cr suffixes
- **Normalization in code**: dates (ISO, day-first, year-less dates resolved from the statement period), amounts (thousand separators, parentheses, `1.234,56`), currencies to ISO codes
- **Page-break de-duplication**: rows repeated at the top of the next page are dropped; identical rows on the same page are kept
- **Background processing** with Celery + Redis; the UI polls until done
- **PII masking**: account numbers stored as `XXXXXXXX1234` by default
- **Confidence scores and token usage** per page
- **CSV export**

## Architecture

```
bank-statement-parser/
├── backend/                     # FastAPI + Celery
│   ├── main.py                  # API app
│   ├── app/
│   │   ├── worker.py            # Celery app and processing task
│   │   ├── api/routes/          # upload, statements, transactions, export
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Response/request models
│   │   └── services/
│   │       ├── pdf_service.py          # PDF pages -> JPEG, sized for the model
│   │       ├── vision_service.py       # One page -> structured JSON via Groq
│   │       ├── statement_parser.py     # Merge pages, normalize dates/amounts/types
│   │       ├── statement_processor.py  # Pipeline + persistence
│   │       └── storage_service.py      # Upload storage (hash-named files)
│   ├── alembic/                 # Database migrations
│   └── tests/
├── frontend/                    # React 19 + Vite + Tailwind
├── start-backend.sh             # API (runs migrations first)
├── start-worker.sh              # Celery worker
└── start-frontend.sh
```

Upload flow: `POST /api/upload` stores the PDF and queues a task. The worker renders pages, extracts them, merges results and marks the statement `completed` or `failed`. The frontend polls `GET /api/statements/{id}` meanwhile.

## Prerequisites

- Python 3.10+
- Node.js 18+
- Redis (`brew install redis && brew services start redis`, or `docker run -d -p 6379:6379 redis`)
- A [Groq API key](https://console.groq.com/keys)

## Setup

```bash
cp backend/.env.example backend/.env   # then set GROQ_API_KEY
cp frontend/.env.example frontend/.env
```

## Running

Three terminals from the project root:

```bash
./start-backend.sh    # API on http://localhost:8000, docs at /docs
./start-worker.sh     # Celery worker
./start-frontend.sh   # UI on http://localhost:5173
```

The backend script creates `backend/venv`, installs dependencies and applies migrations.

## Configuration

All settings live in `backend/.env` (see `.env.example`). The ones you are most likely to change:

| Setting | Default | Notes |
| --- | --- | --- |
| `GROQ_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Any Groq model that accepts images |
| `PAGE_CONCURRENCY` | `3` | Lower it if you hit Groq rate limits |
| `GROQ_MAX_TOKENS` | `8192` | Pages that exceed it fail with a "truncated" error instead of silently losing rows |
| `PDF_DPI` | `200` | Images are also shrunk to stay under Groq's 4MB image limit |
| `MASK_PII` | `True` | Mask account numbers before storing |
| `DATABASE_URL` | `sqlite:///./database.db` | Run `alembic upgrade head` after changing |

## API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/upload` | Upload a PDF. `202` on success; `409` with `existing_statement_id` for a duplicate (a failed duplicate is reprocessed instead) |
| `GET` | `/api/statements` | List. `page`, `limit`, `status`, `search` |
| `GET` | `/api/statements/{id}` | Details, status and `error_message` |
| `DELETE` | `/api/statements/{id}` | Delete statement, data and PDF |
| `POST` | `/api/statements/{id}/reprocess` | Run extraction again |
| `GET` | `/api/statements/{id}/transactions` | `page`, `limit`, `type`, `date_from`, `date_to`, `min_amount`, `max_amount`, `search`, `sort_by`, `sort_order` |
| `GET` | `/api/transactions` | Same filters across statements, plus `statement_ids` |
| `GET` | `/api/statements/{id}/summary` | Credit/debit totals and counts |
| `GET` / `PUT` | `/api/statements/{id}/schema` | Detected columns; update types and display names |
| `GET` | `/api/statements/{id}/metadata` | Raw extraction, token usage, confidence, logs |
| `GET` | `/api/statements/{id}/file` | Original PDF |
| `GET` | `/api/statements/{id}/csv` | CSV export |

Errors are returned as `{"error": true, "message": "..."}`.

## Development

```bash
cd backend
source venv/bin/activate
pip install pytest
pytest                                              # tests use a temp DB and a fake model
alembic revision --autogenerate -m "describe change" # after changing models
```

```bash
cd frontend
npm run dev
npm run build
npm run lint
```

## Security notes

- There is no authentication. Run it locally or put it behind one before exposing it.
- Statement PDFs and extracted data are stored unencrypted in `backend/uploads` and the database.
- Page images are sent to Groq for extraction.

## License

GNU General Public License v2.0. See [LICENSE](LICENSE).
