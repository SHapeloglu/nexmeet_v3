@echo off
echo 🎥 NexMeet Video Konferans Baslatiliyor...

cd /d "%~dp0\.."

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python bulunamadi. Python 3.9+ yukleyin.
    pause
    exit /b 1
)

if not exist "venv" (
    echo 📦 Sanal ortam olusturuluyor...
    python -m venv venv
)

call venv\Scripts\activate
pip install -q -r backend\requirements.txt

echo.
echo ✅ NexMeet hazir!
echo 🌐 Adres: http://localhost:8000
echo 📋 Durdurmak icin: Ctrl+C
echo.

cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
