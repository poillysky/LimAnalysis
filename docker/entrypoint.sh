#!/bin/sh
set -e

role="${1:-app}"

case "$role" in
  app)
    uvicorn app.main:app --host 127.0.0.1 --port 8000 &
    exec nginx -g "daemon off;"
    ;;
  api)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  collector)
    exec python -m collector.worker
    ;;
  agg)
    exec python -m processor.agg_worker
    ;;
  *)
    exec "$@"
    ;;
esac
