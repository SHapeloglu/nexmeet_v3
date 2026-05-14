@echo off
echo ==========================================
echo   NexMeet Uzak Kontrol Ajani
echo ==========================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python bulunamadi. https://python.org adresinden yukleyin.
    pause & exit /b 1
)

echo Gerekli paketler yukleniyor...
pip install -q pyautogui mss websockets pillow

echo.
echo Ajan baslatiliyor...
python agent.py %*
pause
