#!/usr/bin/env bash
# Jalankan Live Polling di komputer lokal (macOS/Linux).
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "Membuat virtual environment..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
echo
echo "Server jalan di http://localhost:8000"
echo "  Admin      : http://localhost:8000/admin"
echo "  Partisipan : http://localhost:8000"
echo
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
