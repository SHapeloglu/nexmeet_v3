#!/bin/bash
clear
echo ""
echo " ╔═══════════════════════════════════════╗"
echo " ║     NexMeet Uzak Kontrol Ajanı        ║"
echo " ╚═══════════════════════════════════════╝"
echo ""

# Python kontrolü
if ! command -v python3 &> /dev/null; then
    echo " ❌ Python3 bulunamadı! Kurmak için:"
    echo "    sudo apt install python3 python3-pip"
    exit 1
fi

# Linux'ta pyautogui için gerekli sistem paketi
echo " 📦 Sistem bağımlılıkları kontrol ediliyor..."
if ! python3 -c "import Xlib" 2>/dev/null; then
    echo " 📥 python3-xlib kuruluyor (sudo şifresi gerekebilir)..."
    sudo apt-get install -y python3-xlib scrot 2>/dev/null || true
fi

# pip paketleri
echo " 📦 Python paketleri kuruluyor..."
pip3 install -q pyautogui mss websockets pillow 2>/dev/null || \
pip3 install -q pyautogui mss websockets pillow --break-system-packages 2>/dev/null
echo " ✅ Paketler hazır!"
echo ""

# Sunucu adresi
read -p " 🌐 Sunucu adresi (örn: ws://192.168.1.75:8000): " SERVER
SERVER=${SERVER:-ws://localhost:8000}

# Oturum kodu
read -p " 🔑 Oturum kodu (NexMeet'ten kopyala): " SESSION
if [ -z "$SESSION" ]; then
    echo " ❌ Oturum kodu boş olamaz!"
    exit 1
fi

# Ekran seçimi
echo ""
echo " 🖥️  Hangi ekranı paylaşmak istiyorsunuz?"
echo " [1] Birinci ekran (varsayılan)"
echo " [2] İkinci ekran"
read -p " Seçiminiz (1/2): " MONITOR
MONITOR=${MONITOR:-1}

echo ""
echo " 🚀 Ajan başlatılıyor..."
echo " ⚠️  Durdurmak için: Ctrl+C"
echo ""

# agent.py'nin bulunduğu dizine git
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python3 agent.py --server "$SERVER" --session "$SESSION" --monitor "$MONITOR" --nogui

echo ""
echo " Ajan durduruldu."
