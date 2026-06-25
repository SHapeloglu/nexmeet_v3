# 🎥 NexMeet — Gerçek Zamanlı Video Konferans

WebRTC tabanlı, **ses klonlamalı anlık çeviri**, **uzak masaüstü kontrolü** ve **dosya paylaşımı** özelliklerine sahip modern video konferans platformu.

> 🌐 **Canlı Demo:** [nexmeet.powerbi.com.tr](https://nexmeet.powerbi.com.tr)

---

## ✨ Özellikler

| Özellik | Açıklama |
|---------|----------|
| 🎥 **WebRTC Video/Ses** | P2P bağlantı, düşük gecikme |
| 🌐 **Anlık Ses Çevirisi** | Türkçe konuş → İngilizce klon sesle karşıya gitsin |
| 🖥️ **Ekran Paylaşımı** | Tüm ekran veya sekme paylaşımı |
| 🕹️ **Uzak Masaüstü Kontrolü** | Karşı tarafın bilgisayarını fare/klavye ile kontrol et |
| 📁 **Dosya Paylaşımı** | Sürükle-bırak, max 100 MB, güvenli MIME doğrulaması |
| 💬 **Sohbet** | Oda geçmişli (son 50 mesaj), gerçek zamanlı |
| 🔴 **Toplantı Kaydı** | Yerel kayıt, WebM formatında indirme |
| 🔒 **Token Tabanlı Auth** | Her katılımcı için 1 saatlik join token |
| 📡 **TURN Sunucusu** | Simetrik NAT arkasındaki kullanıcılar için |

---

## 🏗️ Mimari

```
┌─────────────────────────────────────────────────────┐
│                    KULLANICI TARAYICI               │
│                                                     │
│  Lobby → Token Al → WebSocket → WebRTC P2P         │
│                                                     │
│  [Mic] [Cam] [Ekran] [Kayıt] [Chat] [Dosya] [🌐]  │
└───────────────────────┬─────────────────────────────┘
                        │  WebSocket / HTTP
                        ▼
┌─────────────────────────────────────────────────────┐
│           NexMeet Backend (FastAPI)                 │
│           AWS EC2 c7i-flex.large                    │
│           ***ESKI-IP***                              │
│                                                     │
│  • WebSocket sinyalizasyon (offer/answer/ICE)       │
│  • Join token yönetimi                              │
│  • Dosya upload/download proxy                      │
│  • TTS proxy (/api/tts/*)                           │
│  • Uzak kontrol oturum yönetimi                     │
│  • Nginx + SSL (nexmeet.powerbi.com.tr)             │
└──────────────┬──────────────────────────────────────┘
               │  HTTP (internal)
               ▼
┌─────────────────────────────────────────────────────┐
│         KokoClone TTS Service (FastAPI)             │
│         AWS EC2 g4dn.xlarge (NVIDIA T4 GPU)         │
│         ***ESKI-IP***:5000                          │
│                                                     │
│  Whisper STT → Google Translate → ChatterboxTTS    │
│  (Türkçe ses)  (TR→EN metin)    (klonlanmış ses)   │
└─────────────────────────────────────────────────────┘
```

---

## 📁 Proje Yapısı

```
nexmeet/
├── backend/
│   ├── main.py              # FastAPI uygulaması — tüm endpoint'ler
│   ├── requirements.txt     # Python bağımlılıkları
│   ├── tts/
│   │   ├── chunker.py       # TTS ses chunk yönetimi
│   │   ├── engine.py        # TTS pipeline motor
│   │   └── queue.py         # TTS kuyruk sistemi
│   └── app.js               # Node.js yardımcı script
├── frontend/
│   ├── index.html           # Tek sayfa uygulama (SPA)
│   └── static/
│       ├── css/style.css    # Tüm stiller
│       ├── js/app.js        # WebRTC + tüm UI mantığı
│       └── agent/           # İndirilebilir uzak kontrol ajanı
│           ├── agent.py
│           ├── linux_agent.sh
│           └── windows_agent.bat
├── agent/                   # Geliştirici agent klasörü
│   ├── agent.py             # Uzak kontrol ajanı (Python)
│   ├── linux_agent.sh       # Linux başlatma scripti
│   ├── windows_agent.bat    # Windows başlatma scripti
│   └── requirements.txt
├── docker/
│   ├── Dockerfile           # Docker image
│   ├── docker-compose.yml   # Docker Compose yapılandırması
│   └── backend/             # Docker için backend kopyası
├── scripts/
│   ├── start.sh             # Linux/macOS başlatma scripti
│   └── start.bat            # Windows başlatma scripti
├── uploads/                 # Yüklenen dosyalar (git'e dahil değil)
├── .env.example             # Ortam değişkenleri şablonu
└── start.bat                # Kök dizin Windows başlatma
```

---

## ⚙️ Ortam Değişkenleri

`.env.example` dosyasını `.env` olarak kopyalayıp doldurun:

```bash
cp .env.example .env
```

| Değişken | Açıklama | Örnek |
|----------|----------|-------|
| `SECRET_KEY` | JWT imzalama anahtarı (min 32 karakter) | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ALLOWED_ORIGINS` | CORS için izin verilen origin'ler (virgülle ayrılmış) | `https://nexmeet.powerbi.com.tr` |
| `MAX_FILE_SIZE_MB` | Maksimum dosya yükleme boyutu | `100` |
| `UPLOADS_DIR` | Yüklenen dosyaların kaydedileceği klasör | `uploads` |
| `HOST` | Sunucu dinleme adresi | `0.0.0.0` |
| `PORT` | Sunucu portu | `8000` |
| `TTS_SERVICE_URL` | KokoClone TTS servis adresi | `http://***ESKI-IP***:5000` |
| `TTS_API_KEY` | TTS servisi ile paylaşılan gizli anahtar | `nexmeet-secret-key-123` |

> ⚠️ `TTS_API_KEY` değeri, KokoClone TTS servisindeki `API_KEY` ile **birebir aynı** olmalıdır.

---

## 🚀 Kurulum

### Yerel Geliştirme

**Linux / macOS:**
```bash
git clone https://github.com/SHapeloglu/nexmeet.git
cd nexmeet
cp .env.example .env
# .env dosyasını düzenle

bash scripts/start.sh
# → http://localhost:8000
```

**Windows:**
```bat
git clone https://github.com/SHapeloglu/nexmeet.git
cd nexmeet
copy .env.example .env
REM .env dosyasını düzenle

scripts\start.bat
REM → http://localhost:8000
```

**Manuel kurulum:**
```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt

cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker ile Çalıştırma

```bash
cp .env.example .env
# .env dosyasını düzenle

cd docker
docker-compose up -d

# Logları izle
docker-compose logs -f
```

### AWS EC2 (Production)

**Gereksinimler:**
- Ubuntu 24.04
- Python 3.11+
- Nginx
- SSL sertifikası (Let's Encrypt)

```bash
# 1. Bağımlılıkları kur
sudo apt update && sudo apt install -y python3.11 python3.11-venv nginx certbot

# 2. Projeyi klonla
cd /home/ubuntu
git clone https://github.com/SHapeloglu/nexmeet.git
cd nexmeet

# 3. Sanal ortam oluştur
python3.11 -m venv venv311
source venv311/bin/activate
pip install -r backend/requirements.txt

# 4. .env dosyasını oluştur
cp .env.example .env
nano .env

# 5. systemd servisini kur
sudo cp nexmeet.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nexmeet.service
sudo systemctl start nexmeet.service
```

**systemd servis dosyası** (`/etc/systemd/system/nexmeet.service`):
```ini
[Unit]
Description=NexMeet Backend
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/nexmeet/backend
EnvironmentFile=/home/ubuntu/nexmeet/.env
Environment="PATH=/home/ubuntu/nexmeet/venv311/bin"
ExecStart=/home/ubuntu/nexmeet/venv311/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

---

## 📡 API Referansı

### HTTP Endpoints

#### `GET /`
Ana sayfa (Lobby).

#### `GET /room/{room_id}`
Oda sayfası (SPA yönlendirme).

#### `GET /api/room/{room_id}/info`
Oda bilgisi — mevcut katılımcı listesi.

```json
{
  "room_id": "abc123",
  "peer_count": 2,
  "peers": [
    {"id": "peer1", "name": "Ali"},
    {"id": "peer2", "name": "Veli"}
  ]
}
```

#### `POST /api/join-token` ⚡ Rate: 20/dk
Join token oluştur.

```json
// Request
{"name": "Ali", "room_id": "abc123", "peer_id": "peer-xyz"}

// Response
{"token": "eyJhbGci..."}
```

#### `POST /api/upload/{room_id}` ⚡ Rate: 10/dk
Dosya yükle (multipart/form-data).

| Alan | Tip | Açıklama |
|------|-----|----------|
| `file` | File | Yüklenecek dosya |
| `peer_id` | string | Yükleyenin peer ID'si |
| `uploader_name` | string | Yükleyenin adı |
| `token` | string | Join token |

#### `GET /api/download/{file_id}?token=...`
Dosya indir — token zorunlu.

#### `GET /api/room/{room_id}/files?token=...`
Odadaki dosyaları listele.

---

### TTS Endpoints

#### `POST /api/tts/synthesize` ⚡ Rate: 30/dk
Ses kaydını KokoClone TTS servisine proxy'le.

```json
// Request
{
  "token": "join-token",
  "audio_base64": "<WAV base64>",
  "source_lang": "tr",
  "target_lang": "en",
  "session_id": "oturum-id"
}

// Response (KokoClone'dan)
{
  "audio_base64": "<üretilen WAV base64>",
  "duration_ms": 4200
}
```

#### `POST /api/tts/voice-profile` ⚡ Rate: 5/dk
Kullanıcının ses profilini kaydet.

#### `GET /api/tts/voice-profile/status?token=...`
Kullanıcının ses profilinin var olup olmadığını kontrol et.

---

### Uzak Kontrol Endpoints

#### `POST /api/control/request`
Uzak kontrol isteği başlat.

#### `POST /api/control/respond`
Uzak kontrol isteğini onayla/reddet.

#### `POST /api/control/stop`
Uzak kontrol oturumunu sonlandır.

---

### WebSocket Endpoints

#### `WS /ws/{room_id}/{peer_id}?token=...`
Ana oda sinyalizasyon kanalı.

**Gönderilen mesaj tipleri:**

| Tip | Açıklama |
|-----|----------|
| `offer` | WebRTC SDP offer |
| `answer` | WebRTC SDP answer |
| `ice-candidate` | ICE adayı |
| `chat` | Sohbet mesajı |
| `media-state` | Mikrofon/kamera durumu |
| `screen-share-started` | Ekran paylaşımı başladı |
| `screen-share-stopped` | Ekran paylaşımı durdu |
| `recording-started` | Kayıt başladı |
| `recording-stopped` | Kayıt durdu |
| `tts-audio` | TTS ile çevrilmiş ses |
| `file-chunk` | P2P dosya aktarımı |
| `control-request` | Uzak kontrol talebi |
| `control-response` | Uzak kontrol yanıtı |

**Alınan sunucu mesajları:**

| Tip | Açıklama |
|-----|----------|
| `room-joined` | Odaya katılındı (peer listesi + chat geçmişi) |
| `peer-joined` | Yeni katılımcı geldi |
| `peer-left` | Katılımcı ayrıldı |

#### `WS /ws/agent/{agent_id}?token=...&session_id=...`
Uzak kontrol ajanı kanalı (kontrol edilmek isteyen bilgisayar).

#### `WS /ws/control/{session_id}/{controller_peer_id}?token=...`
Kontrolcü kanalı (kontrol eden taraf).

---

## 🌐 Anlık Ses Çevirisi (TTS)

### Nasıl Çalışır?

```
Kullanıcı 🎤 konuşur (TR)
      │
      ▼ (3 saniyelik chunk'lar)
 MediaRecorder API (WAV)
      │
      ▼
POST /api/tts/synthesize
      │
      ▼
 KokoClone TTS Service:
 1. Whisper STT  → "Merhaba nasılsın"
 2. Google Translate → "Hello how are you"
 3. ChatterboxTTS → 🔊 (konuşmacının sesiyle)
      │
      ▼
 WebSocket tts-audio mesajı
      │
      ▼
 Odadaki herkes duyar 🔊
```

### Ses Profili Kaydı

Ses klonlama için kullanıcının önce ses profili kaydetmesi gerekir:

1. 🌐 butonuna tıkla
2. "Ses Profili Kaydet" → 5 saniye konuş
3. Profil kaydedilince çeviri otomatik başlar

Profil yoksa Chatterbox'ın varsayılan sesi kullanılır.

### Gecikme

| Adım | Süre |
|------|------|
| Whisper STT (GPU) | ~1-2 sn |
| Google Translate | ~0.5 sn |
| ChatterboxTTS (GPU) | ~2-3 sn |
| **Toplam** | **~4-6 sn** |

---

## 🕹️ Uzak Masaüstü Kontrolü

### Kurulum (Kontrol Edilecek Bilgisayar)

```bash
# Agent bağımlılıkları
pip install pyautogui mss websockets pillow

# Çalıştır
python agent/agent.py --server wss://nexmeet.powerbi.com.tr --session OTURUM_ID
```

veya indirilebilir scriptler:
- **Windows:** `windows_agent.bat`
- **Linux:** `linux_agent.sh`

### Akış

1. **A** kullanıcısı → B'ye "Kontrolü Al" isteği gönderir
2. **B** kullanıcısı → İsteği onaylar (veya reddeder)
3. **A** → B'nin ekranını canlı görür, fare/klavye ile kontrol eder
4. Kontrol sonlandırmak için "Kontrolü Durdur"

### Güvenlik

- Yalnızca onaylı oturumlar aktif
- İzin verilen komutlar: `mouse-move`, `mouse-click`, `mouse-scroll`, `key-press`, `key-type`, `stop-control`
- Her iki taraf da oturumu sonlandırabilir

---

## 🔒 Güvenlik

### Token Sistemi
- Her katılımcı `/api/join-token` ile benzersiz token alır
- Tokenlar 1 saat geçerli, sonra otomatik silinir
- Tüm korumalı endpoint'ler token doğrulaması gerektirir

### Dosya Güvenliği

**Yasaklı uzantılar:**
`.exe`, `.bat`, `.cmd`, `.sh`, `.ps1`, `.msi`, `.dll`, `.so`, `.jar`, `.py`, `.php` ve diğer çalıştırılabilir dosyalar

**İzin verilen MIME tipleri:**
PDF, Word, Excel, PowerPoint, görseller (JPG/PNG/GIF/WebP), ses/video, ZIP

### Rate Limiting

| Endpoint | Limit |
|----------|-------|
| `/api/join-token` | 20/dakika |
| `/api/upload/*` | 10/dakika |
| `/api/download/*` | 30/dakika |
| `/api/tts/synthesize` | 30/dakika |
| `/api/tts/voice-profile` | 5/dakika |

### CORS
Production'da `ALLOWED_ORIGINS` ile yalnızca belirlenen domain'lere izin verilir.

---

## 🔧 Sorun Giderme

### Kamera/Mikrofon açılmıyor
Tarayıcı kamera iznine HTTPS üzerinden erişebilir. Yerel geliştirmede `http://localhost:8000` çalışır; dış IP ile açarken HTTPS gereklidir.

### WebSocket bağlantısı kurulamıyor
```bash
# Nginx'in WebSocket proxy ayarları kontrol et
sudo nginx -t
sudo systemctl status nginx

# Backend çalışıyor mu?
sudo systemctl status nexmeet.service
```

### TTS çalışmıyor (503)
```bash
# .env dosyasında TTS_SERVICE_URL tanımlı mı?
grep TTS /home/ubuntu/nexmeet/.env

# TTS servisi erişilebilir mi?
curl http://***ESKI-IP***:5000/health
```

### TTS "Geçersiz API key" hatası
```bash
# Backend'deki key
grep TTS_API_KEY /home/ubuntu/nexmeet/.env

# TTS servisindeki key
sudo cat /proc/$(systemctl show -p MainPID kokoro-tts.service | cut -d= -f2)/environ | tr '\0' '\n' | grep API_KEY
# İkisi aynı olmalı!
```

### Servis logları
```bash
sudo journalctl -u nexmeet.service -f
sudo journalctl -u nexmeet.service -n 100 --no-pager
```

---

## 🖥️ Servis Yönetimi (AWS)

```bash
# Başlat
sudo systemctl start nexmeet.service

# Durdur
sudo systemctl stop nexmeet.service

# Yeniden başlat
sudo systemctl restart nexmeet.service

# Durumu kontrol et
sudo systemctl status nexmeet.service

# Logları izle
sudo journalctl -u nexmeet.service -f

# Nginx yeniden yükle
sudo nginx -s reload
```

---

## 📦 Bağımlılıklar

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
websockets==13.1
python-multipart==0.0.12
aiofiles==24.1.0
slowapi          # Rate limiting
httpx            # TTS proxy HTTP client
python-dotenv
```

**Uzak Kontrol Ajanı:**
```
pyautogui        # Fare/klavye kontrolü
mss              # Ekran yakalama
websockets       # WS bağlantısı
pillow           # Görüntü işleme
```

---

## 🗂️ İlgili Repolar

| Repo | Açıklama |
|------|----------|
| [nexmeet](https://github.com/SHapeloglu/nexmeet) | Bu repo — Backend + Frontend |
| [nexmeet-kokoro-tts-service](https://github.com/SHapeloglu/nexmeet-kokoro-tts-service) | KokoClone TTS servisi |

---

## 📋 Altyapı

| Bileşen | Detay |
|---------|-------|
| Backend sunucusu | AWS EC2 c7i-flex.large |
| Backend IP | ***ESKI-IP*** (Elastic IP) |
| TTS sunucusu | AWS EC2 g4dn.xlarge |
| TTS IP | ***ESKI-IP*** (Elastic IP) |
| Domain | nexmeet.powerbi.com.tr |
| SSL | Let's Encrypt / Nginx |
| TURN | coturn (aynı backend sunucusu, port 3478) |
| GPU | NVIDIA T4, CUDA, PyTorch 2.6.0 |

---

## 🏷️ Lisans

Bu proje NexMeet ekibine aittir. İzinsiz kullanım ve dağıtım yasaktır.
