@echo off
REM Jalankan Live Polling di komputer lokal (Windows).
cd /d "%~dp0"
if not exist ".venv" (
  echo Membuat virtual environment...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo.
echo Server jalan di http://localhost:8000
echo   Admin      : http://localhost:8000/admin
echo   Partisipan : http://localhost:8000
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
