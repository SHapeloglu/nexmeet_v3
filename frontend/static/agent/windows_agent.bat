@echo off
REM NexMeet uzak kontrol ajaninin Windows kurulum ve baslatma dosyasi.
REM Calistirma: cift tiklayarak ya da cmd icinden elle. Zamanlayici yok.
REM Gerekli: Python 3.9+ (PATH'te olmali) ve internet (pip paketleri icin).
REM Paketleri (pyautogui, mss, websockets, pillow) kurar, sunucu adresi, oturum kodu ve anahtari sorar, agent.py'yi baslatir.
REM Sistem dosyalarini degistirmez. Durdurmak icin pencereyi kapatin veya fareyi sol ust koseye goturun.
title NexMeet - Uzak Kontrol Ajani

echo.
echo  =========================================
echo       NexMeet - Uzak Kontrol Ajani
echo  =========================================
echo.

:: Python kontrolu
REM Python komutu PATH'te var mi kontrol eder. Yoksa kurulum yapilamaz; kullaniciya yonerge gosterilip cikilir.
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
REM Paketleri global Python'a kurar (sanal ortam kullanilmaz). Her acilista calisir; internet yoksa uzun surebilir.
REM Hata olursa ajan calistirilmadan cikilir.
python -m pip install -q pyautogui mss websockets pillow
if %errorlevel% neq 0 (
    echo  HATA: Paketler kurulamadi!
    pause
    exit /b 1
)
echo  Paketler hazir!
echo.

:: Sunucu adresi
REM Kullaniciya sunucu adresini sorar. set /p girilen metni degiskene atar. Bos birakilirsa asagida localhost varsayilir.
set /p SERVER="  Sunucu adresi (ornek: ws://192.168.2.75:8000): "
if "%SERVER%"=="" set SERVER=ws://localhost:8000

:: Oturum kodu
REM Oturum kodu NexMeet web arayuzunden kopyalanir. Bos ise ajan baslamaz.
set /p SESSION="  Oturum kodu (NexMeet'ten kopyala): "
if "%SESSION%"=="" (
    echo  HATA: Oturum kodu bos olamaz!
    pause
    exit /b 1
)

:: Ajan anahtari
REM DIKKAT: ajan anahtari bu pencerede gorunur; gizli tutulmaz. Ekran paylasiminda dikkat edin. Bos ise ajan baslamaz.
set /p KEY="  Ajan anahtari (NexMeet'ten kopyala): "
if "%KEY%"=="" (
    echo  HATA: Ajan anahtari bos olamaz!
    pause
    exit /b 1
)

:: Ekran secimi
echo.
echo  Hangi ekrani paylasmak istiyorsunuz?
echo  [1] Birinci ekran (varsayilan)
echo  [2] Ikinci ekran
REM Ekran secimi: 1 birinci ekran, 2 ikinci ekran. Bos birakilirsa 1 secilir (asagidaki satir).
set /p MONITOR="  Seciminiz (1/2): "
if "%MONITOR%"=="" set MONITOR=1

echo.
echo  Ajan baslatiliyor...
echo  Durdurmak icin: fareyi sol ust koseye gotur veya pencereyi kapat
echo.

:: agent.py bu bat dosyasiyla ayni klasorde olmali
REM Bat dosyasinin bulundugu klasore gecilir ki agent.py bulunabilsin.
cd /d "%~dp0"
REM Anahtar --key ile degil NEXMEET_AGENT_KEY ortam degiskeniyle verilir. Neden: komut satiri argumanlari
REM surec listesinde (ps / Gorev Yoneticisi komut satiri sutunu) herkese gorunur, ortam degiskeni gorunmez.
REM Ortam degiskeni set ile bu pencereye atanir; agent.py bunu okur.
set "NEXMEET_AGENT_KEY=%KEY%"
REM Ajani baslatir. --nogui: yerel ekranda ek pencere acilmasini engeller. Ajan kapanana kadar satir burada bekler.
python agent.py --server %SERVER% --session %SESSION% --monitor %MONITOR% --nogui

echo.
echo  Ajan durduruldu.
REM pause: pencere hemen kapanmasin diye kullanicidan bir tusa basmasini bekler; hata mesajini okumak icin.
pause
