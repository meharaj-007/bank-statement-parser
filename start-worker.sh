#!/bin/bash

# Bank Statement Parser - Celery worker startup script

set -e
cd "$(dirname "$0")/backend"

if [ ! -d "venv" ]; then
    echo "ERROR: backend/venv not found. Run ./start-backend.sh first."
    exit 1
fi

source venv/bin/activate

if ! redis-cli ping > /dev/null 2>&1; then
    echo "ERROR: Redis is not responding."
    echo "Start it with: brew services start redis  (or: docker run -d -p 6379:6379 redis)"
    exit 1
fi

echo "Starting Celery worker"
exec celery -A app.worker worker --loglevel=info --concurrency="${WORKER_CONCURRENCY:-2}"
