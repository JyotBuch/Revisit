#!/usr/bin/env bash
set -e

alembic upgrade head

exec gunicorn -k uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:${PORT:-8000} --timeout 120 app.main:app
