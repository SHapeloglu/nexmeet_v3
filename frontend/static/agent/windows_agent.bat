@echo off
title NexMeet - Uzak Kontrol Ajani

echo.
echo  =========================================
echo       NexMeet - Uzak Kontrol Ajani
echo  =========================================
echo.

:: Python kontrolu
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  HATA: Python bulunamadi!
    echo  https://python.org adresinden Python 3.9+ indirin.
    echo  Kurulumda "Add Python to PATH" kutusunu isaretle!
    pause
    exit /b 1
)

:: Paket kurulumu
echo  Gerekli paketler kuruluyor...
python -m pip install -q pyautogui mss websockets pillow
if %errorlevel% neq 0 (
    echo  HATA: Paketler kurulamadi!
    pause
    exit /b 1
)
echo  Paketler hazir!
echo.

:: Sunucu adresi
set /p SERVER="  Sunucu adresi (ornek: ws://192.168.2.75:8000): "
if "%SERVER%"=="" set SERVER=ws://localhost:8000

:: Oturum kodu
set /p SESSION="  Oturum kodu (NexMeet'ten kopyala): "
if "%SESSION%"=="" (
    echo  HATA: Oturum kodu bos olamaz!
    pause
    exit /b 1
)

:: Ekran secimi
echo.
echo  Hangi ekrani paylasmak istiyorsunuz?
echo  [1] Birinci ekran (varsayilan)
echo  [2] Ikinci ekran
set /p MONITOR="  Seciminiz (1/2): "
if "%MONITOR%"=="" set MONITOR=1

echo.
echo  Ajan baslatiliyor...
echo  Durdurmak icin: fareyi sol ust koseye gotur veya pencereyi kapat
echo.

:: agent.py bu bat dosyasiyla ayni klasorde olmali
cd /d "%~dp0"
python agent.py --server %SERVER% --session %SESSION% --monitor %MONITOR% --nogui

echo.
echo  Ajan durduruldu.
pause
