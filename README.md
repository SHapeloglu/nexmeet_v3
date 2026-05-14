# 🎥 NexMeet — Video Konferans Uygulaması

Google Meet benzeri, tam özellikli web tabanlı video konferans uygulaması.

## ✨ Özellikler

| Özellik | Durum |
|---|---|
| 🎥 Çoklu katılımcı video konferansı | ✅ |
| 🎤 Mikrofon açma/kapama | ✅ |
| 📷 Kamera açma/kapama | ✅ |
| 🖥️ Ekran paylaşımı | ✅ |
| ⏺️ Toplantı kaydı (WebM) | ✅ |
| 💬 Gerçek zamanlı sohbet | ✅ |
| 🔗 Davet linki | ✅ |
| ⏱️ Toplantı süresi göstergesi | ✅ |
| 🔒 Kurulum gerektirmez | ✅ |

## 🚀 Kurulum & Başlatma

### Gereksinimler
- Python 3.9+
- Modern bir web tarayıcı (Chrome, Firefox, Edge, Safari)

### Linux / macOS

```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

### Windows

`scripts/start.bat` dosyasını çift tıklayın.

### Manuel kurulum

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Ardından tarayıcıda açın: **http://localhost:8000**

### Docker ile

```bash
cd docker
docker-compose up --build
```

## 📱 Kullanım

1. **http://localhost:8000** adresine gidin
2. Adınızı girin
3. **Yeni toplantı**: Oda kodu boş bırakın → "Katıl"
4. **Mevcut toplantıya katıl**: Oda kodunu girin → "Katıl"
5. Toplantı linkini kopyalamak için sağ üstteki oda koduna tıklayın

## 🏗️ Proje Yapısı

```
VideoConference/
├── backend/
│   ├── main.py          # FastAPI + WebSocket sinyal sunucusu
│   └── requirements.txt
├── frontend/
│   ├── index.html       # Ana sayfa
│   └── static/
│       ├── css/style.css
│       └── js/app.js    # WebRTC + UI mantığı
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
└── scripts/
    ├── start.sh
    └── start.bat
```

## 🔧 Teknoloji Yığını

- **Backend**: Python, FastAPI, WebSockets
- **Frontend**: Vanilla JS, WebRTC API, MediaRecorder API
- **Protokol**: WebRTC (P2P video/ses), WebSocket (sinyal)
- **Kayıt**: MediaRecorder API → WebM formatı

## 🌐 Ağ Notları

- **Yerel ağda**: Herhangi ek ayar gerekmez
- **İnternet üzerinden**: Sunucunuzu internet erişimli bir makineye kurun veya ngrok gibi bir tunnel kullanın:
  ```bash
  ngrok http 8000
  ```
- **HTTPS gereksinimi**: Uzak bağlantılarda kamera/mikrofon erişimi için HTTPS gerekebilir

## 📝 Lisans

MIT
