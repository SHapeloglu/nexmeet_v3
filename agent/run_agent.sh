#!/bin/bash
echo "=========================================="
echo "  NexMeet Uzak Kontrol Ajanı"
echo "=========================================="
echo ""
echo "Gerekli paketler yükleniyor..."
pip install -q pyautogui mss websockets pillow
echo ""
echo "Ajan başlatılıyor..."
python3 agent.py "$@"
