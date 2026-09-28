# Repository Guidelines

## Project Structure & Module Organization

`backend/app/` contains FastAPI routes, schemas, models, services, and worker logic. Database migrations are in `backend/alembic/`; pytest tests are in `backend/tests/`. `frontend/src/` contains the React/Vite application, including pages and API clients.

## Build, Test, and Development Commands

From the root, run `./start-backend.sh`, `./start-worker.sh`, and `./start-frontend.sh` in separate terminals. The backend launcher installs requirements and applies migrations; the Celery worker requires Redis. In `frontend/`, use `npm ci`, `npm run dev`, `npm run build`, and `npm run lint`.

## Coding Style & Naming Conventions

Use four-space indentation and snake_case functions/modules in Python. Match the existing TypeScript formatting and PascalCase React components. Keep extraction logic in services, HTTP handling in routes, and frontend requests in API clients. Use Alembic revisions for schema changes.

## Testing Guidelines

Activate the backend virtual environment, then run `pytest` from `backend/`. Tests use a temporary database and fake model responses. Add `test_*.py` regression cases for extraction, parsing, and API behavior. Run frontend lint/build and manually verify upload, processing, detail, and export flows. No frontend test script is configured.

## Commit & Pull Request Guidelines

Recent history mostly uses imperative subjects describing API or extraction changes. Keep commits focused on one change. In pull requests, explain the problem, resulting behavior, and validation performed; link an issue when applicable. Include screenshots for visible UI changes and call out configuration or migration changes. These are contributor expectations, not a claim of enforced branch rules.

## Security & Configuration

Configure `backend/.env` using its example file and supply the required model API key. Keep credentials, uploaded statements, and real financial records out of commits and fixtures. Document new environment variables without including their values.
