#!/bin/bash
# NexMeet uzak kontrol ajaninin Linux kurulum ve baslatma betigi.
# Calistirma: kullanici elle calistirir (bash linux_agent.sh). Zamanlayici yok.
# Gerekli: python3 ve sudo yetkisi (eksik sistem paketi icin apt kurulumu sorar).
# Python paketlerini (pyautogui, mss, websockets, pillow) kurar ve agent.py'yi baslatir.
# Sistem dosyalarini degistirmez. Durdurmak icin Ctrl+C.
clear
echo ""
echo " ╔═══════════════════════════════════════╗"
echo " ║     NexMeet Uzak Kontrol Ajanı        ║"
echo " ╚═══════════════════════════════════════╝"
echo ""

# ── Python kontrolü ──────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo " ❌ Python3 bulunamadı! Kurmak için:"
    echo "    sudo apt install python3 python3-pip"
    exit 1
fi

# ── Sistem bağımlılıkları ─────────────────────────────────────────────────────
# pyautogui Linux'ta X11 kütüphanelerine ihtiyaç duyar (python3-xlib, scrot)
# tkinter GUI penceresi için gerekli (python3-tk)
# Bu paketler pip ile KURULAMAZ, mutlaka apt ile kurulmalı
echo " 📦 Sistem bağımlılıkları kontrol ediliyor..."

# Eksik sistem paketlerinin adlarini burada biriktiriyoruz. Liste sonra tek seferde apt ile kurulur.
MISSING_PKGS=""

# Her kontrol basarisiz olursa (|| sonrasi) o paketin adi listeye eklenir.
# 2>/dev/null hata mesajini gizler; amac sadece var/yok bilgisi almak.
python3 -c "import Xlib"    2>/dev/null || MISSING_PKGS="$MISSING_PKGS python3-xlib"
python3 -c "import tkinter" 2>/dev/null || MISSING_PKGS="$MISSING_PKGS python3-tk"
command -v scrot &>/dev/null            || MISSING_PKGS="$MISSING_PKGS scrot"

# Liste bos degilse eksik paketler apt ile kurulmaya calisilir.
if [ -n "$MISSING_PKGS" ]; then
    echo " 📥 Eksik paketler kuruluyor:$MISSING_PKGS"
    echo " (sudo şifresi istenebilir)"
    # DIKKAT: sudo sifre isteyebilir. Betik bu noktada kullanicinin yazmasini bekler.
    sudo apt-get install -y $MISSING_PKGS
    if [ $? -ne 0 ]; then
        echo ""
        echo " ❌ Sistem paketleri kurulamadı!"
        echo "    Lütfen manuel olarak çalıştırın:"
        echo "    sudo apt install python3-xlib python3-tk scrot"
        exit 1
    fi
else
    echo " ✅ Sistem bağımlılıkları hazır."
fi

# ── Python (pip) paketleri ───────────────────────────────────────────────────
echo " 📦 Python paketleri kontrol ediliyor..."

# Ubuntu 23.04+ "externally-managed" hatası verir, --break-system-packages gerekir
# Verilen pip paketini kurar. 1. arguman pip'teki paket adi, 2. arguman Python'da import edilecek modul adidir.
# Modul zaten yuklu ise hicbir sey yapilmaz.
install_pip_pkg() {
    PKG=$1
    MOD=${2:-$1}
    # Modul zaten yukluyse fonksiyon burada biter (return 0).
    python3 -c "import $MOD" 2>/dev/null && return 0
    # Kurulumu 3 denemeyle yapar: once normal, sonra --break-system-packages (Ubuntu 23.04+ 'externally-managed' hatasi icin), sonra --user.
    # Asil basari kontrolu asagida yapilir; burada hata yutulur.
    pip3 install -q "$PKG" 2>/dev/null || \
    pip3 install -q "$PKG" --break-system-packages 2>/dev/null || \
    pip3 install -q "$PKG" --user 2>/dev/null
}

# Ajanin ihtiyac duydugu Python paketleri.
install_pip_pkg "pyautogui"  "pyautogui"
install_pip_pkg "mss"        "mss"
install_pip_pkg "websockets" "websockets"
install_pip_pkg "pillow"     "PIL"

# Kurulum doğrulaması
echo " 🔍 Kurulum doğrulanıyor..."
FAILED=""
# Kurulumdan sonra her modulu tekrar import ederek gercekten yuklendigini dogrular. Basarisiz olanlar FAILED listesine yazilir.
python3 -c "import pyautogui"      2>/dev/null || FAILED="$FAILED pyautogui"
python3 -c "import mss"            2>/dev/null || FAILED="$FAILED mss"
python3 -c "import websockets"     2>/dev/null || FAILED="$FAILED websockets"
python3 -c "from PIL import Image" 2>/dev/null || FAILED="$FAILED pillow"

if [ -n "$FAILED" ]; then
    echo ""
    echo " ❌ Şu paketler kurulamadı:$FAILED"
    echo "    Lütfen manuel deneyin:"
    echo "    pip3 install$FAILED --break-system-packages"
    exit 1
fi

echo " ✅ Tüm paketler hazır!"
echo ""

# ── Bağlantı bilgileri ───────────────────────────────────────────────────────
# Kullanicidan baglanti bilgilerini ister. Sunucu adresi bos birakilirsa ws://localhost:8000 kullanilir.
read -p " 🌐 Sunucu adresi (örn: ws://192.168.1.75:8000): " SERVER
SERVER=${SERVER:-ws://localhost:8000}

read -p " 🔑 Oturum kodu (NexMeet'ten kopyala): " SESSION
# Ajan anahtari ekranda gosterilmez (read -s); oturum kodu hala gorunur.
read -rsp " 🔐 Ajan anahtarı (NexMeet'ten kopyala): " KEY
echo
# Anahtar veya oturum kodu bos ise ajan calismaz; burada cikilir.
if [ -z "$KEY" ]; then
    echo " ❌ Ajan anahtarı boş olamaz!"
    exit 1
fi
if [ -z "$SESSION" ]; then
    echo " ❌ Oturum kodu boş olamaz!"
    exit 1
fi

# Ekran sayısını tespit et
# Bagli ekran sayisini mss ile bulur. mss.monitors listesinin ilk elemani tum ekranlarin birlesimi oldugu icin max(... - 1, 1) ile duzeltilir.
# Hata olursa 1 kabul edilir.
MONITOR_COUNT=$(python3 -c "import mss; s=mss.mss(); print(max(len(s.monitors)-1,1))" 2>/dev/null || echo 1)
echo ""
if [ "$MONITOR_COUNT" -gt 1 ]; then
    echo " 🖥️  $MONITOR_COUNT ekran bulundu:"
    for i in $(seq 1 $MONITOR_COUNT); do
        echo " [$i] Ekran $i"
    done
    # Birden fazla ekran varsa hangi ekranin paylasilacagi sorulur.
    read -p " Seçiminiz (1-$MONITOR_COUNT): " MONITOR
else
    MONITOR=1
fi
# Kullanici bos birakirsa varsayilan olarak 1. ekran secilir.
MONITOR=${MONITOR:-1}

# ── Başlat ───────────────────────────────────────────────────────────────────
echo ""
echo " 🚀 Ajan başlatılıyor..."
echo " ⚠️  Durdurmak için: Ctrl+C"
echo " ⚠️  Acil durdurma: fareyi ekranın SOL ÜST köşesine götür"
echo ""

# agent.py bu betikle ayni klasorde olmali. Betigin kendi klasorunu bulup oraya gecer; boylece nereden calistirilirsa calistirilsin dogru dosya bulunur.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ajani baslatir. --nogui: yerel ekranda ek pencere acilmasini engeller.
# Ajan kapanana kadar (Ctrl+C veya hata) betik burada bekler.
# Anahtar --key ile degil NEXMEET_AGENT_KEY ortam degiskeniyle verilir. Neden: komut satirindaki
# argumanlar ps listesinde herkese gorunur, ortam degiskeni ise gorunmez. Ortam degiskeni sadece
# bu tek komuta atanir (ayni satirda), betigin geri kalanina ve kabuga sizmaz.
NEXMEET_AGENT_KEY="$KEY" python3 agent.py --server "$SERVER" --session "$SESSION" --monitor "$MONITOR" --nogui

echo ""
echo " Ajan durduruldu."
