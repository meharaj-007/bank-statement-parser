#!/bin/bash

# Bank Statement Parser - API server startup script

set -e
cd "$(dirname "$0")/backend"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# Reinstall when requirements.txt changes
if [ ! -f "venv/.installed" ] || [ requirements.txt -nt venv/.installed ]; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
    touch venv/.installed
fi

if [ ! -f ".env" ]; then
    echo "ERROR: backend/.env not found."
    echo "Copy backend/.env.example to backend/.env and set GROQ_API_KEY."
    exit 1
fi

if ! redis-cli ping > /dev/null 2>&1; then
    echo "WARNING: Redis is not responding. Uploads will fail until it is running"
    echo "  (brew services start redis, or: docker run -d -p 6379:6379 redis)"
fi

echo "Applying database migrations..."
alembic upgrade head

PORT=$(grep -E '^PORT=' .env | cut -d= -f2)
PORT=${PORT:-8000}

echo ""
echo "Starting API on http://localhost:$PORT (docs at /docs)"
echo "Start the worker in another terminal: ./start-worker.sh"
echo ""

exec uvicorn main:app --reload --host 0.0.0.0 --port "$PORT"
