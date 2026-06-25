#!/bin/bash
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

MISSING_PKGS=""

python3 -c "import Xlib"    2>/dev/null || MISSING_PKGS="$MISSING_PKGS python3-xlib"
python3 -c "import tkinter" 2>/dev/null || MISSING_PKGS="$MISSING_PKGS python3-tk"
command -v scrot &>/dev/null            || MISSING_PKGS="$MISSING_PKGS scrot"

if [ -n "$MISSING_PKGS" ]; then
    echo " 📥 Eksik paketler kuruluyor:$MISSING_PKGS"
    echo " (sudo şifresi istenebilir)"
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
install_pip_pkg() {
    PKG=$1
    MOD=${2:-$1}
    python3 -c "import $MOD" 2>/dev/null && return 0
    pip3 install -q "$PKG" 2>/dev/null || \
    pip3 install -q "$PKG" --break-system-packages 2>/dev/null || \
    pip3 install -q "$PKG" --user 2>/dev/null
}

install_pip_pkg "pyautogui"  "pyautogui"
install_pip_pkg "mss"        "mss"
install_pip_pkg "websockets" "websockets"
install_pip_pkg "pillow"     "PIL"

# Kurulum doğrulaması
echo " 🔍 Kurulum doğrulanıyor..."
FAILED=""
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
read -p " 🌐 Sunucu adresi (örn: ws://192.168.1.75:8000): " SERVER
SERVER=${SERVER:-ws://localhost:8000}

read -p " 🔑 Oturum kodu (NexMeet'ten kopyala): " SESSION
if [ -z "$SESSION" ]; then
    echo " ❌ Oturum kodu boş olamaz!"
    exit 1
fi

# Ekran sayısını tespit et
MONITOR_COUNT=$(python3 -c "import mss; s=mss.mss(); print(max(len(s.monitors)-1,1))" 2>/dev/null || echo 1)
echo ""
if [ "$MONITOR_COUNT" -gt 1 ]; then
    echo " 🖥️  $MONITOR_COUNT ekran bulundu:"
    for i in $(seq 1 $MONITOR_COUNT); do
        echo " [$i] Ekran $i"
    done
    read -p " Seçiminiz (1-$MONITOR_COUNT): " MONITOR
else
    MONITOR=1
fi
MONITOR=${MONITOR:-1}

# ── Başlat ───────────────────────────────────────────────────────────────────
echo ""
echo " 🚀 Ajan başlatılıyor..."
echo " ⚠️  Durdurmak için: Ctrl+C"
echo " ⚠️  Acil durdurma: fareyi ekranın SOL ÜST köşesine götür"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python3 agent.py --server "$SERVER" --session "$SESSION" --monitor "$MONITOR" --nogui

echo ""
echo " Ajan durduruldu."
