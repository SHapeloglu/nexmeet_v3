@echo off
cd /d "C:\Users\yeliz\Desktop\Projeler\GitHub\NextMeet"

if not exist venv (
    echo Sanal ortam olusturuluyor...
    python -m venv venv
)

call venv\Scripts\activate

echo Bagimliliklar kuruluyor...
pip install -r backend\requirements.txt

echo Sunucu baslatiliyor...
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
pause
