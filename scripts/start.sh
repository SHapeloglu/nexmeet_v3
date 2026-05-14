#!/bin/bash
# NexMeet Başlatma Scripti (Linux/macOS)

echo "🎥 NexMeet Video Konferans Başlatılıyor..."

cd "$(dirname "$0")/.."

# Python kontrolü
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 bulunamadı. Lütfen Python 3.9+ yükleyin."
    exit 1
fi

# Sanal ortam yoksa oluştur
if [ ! -d "venv" ]; then
    echo "📦 Sanal ortam oluşturuluyor..."
    python3 -m venv venv
fi

# Aktive et ve bağımlılıkları yükle
source venv/bin/activate
pip install -q -r backend/requirements.txt

echo ""
echo "✅ NexMeet hazır!"
echo "🌐 Adres: http://localhost:8000"
echo "📋 Durdurmak için: Ctrl+C"
echo ""

cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
