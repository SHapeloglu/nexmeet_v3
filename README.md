# 🎥 NexMeet — Gerçek Zamanlı Video Konferans

WebRTC tabanlı video konferans: **anlık konuşma çevirisi (TR → EN)**, **uzak masaüstü kontrolü**, **dosya paylaşımı**, sohbet, ekran paylaşımı ve toplantı kaydı.

> Canlı: `nexmeet.powerbiegitimi.com`

---

## ✨ Özellikler

| Özellik | Açıklama |
|---------|----------|
| 🎥 WebRTC Video/Ses | P2P bağlantı; sunucu yalnızca sinyalizasyon yapar |
| 🌐 Anlık Çeviri | Türkçe konuşma → İngilizce sentezlenmiş ses (sabit ses, ses klonlama yok) |
| 🖥️ Ekran Paylaşımı | Tüm ekran veya sekme |
| 🕹️ Uzak Masaüstü Kontrolü | Karşı tarafın onayıyla fare/klavye kontrolü (indirilebilir Python ajan) |
| 📁 Dosya Paylaşımı | En fazla **50 MB**, uzantı + MIME doğrulaması, **1 saat sonra otomatik silinir** |
| 💬 Sohbet | Oda geçmişli (son 50 mesaj) |
| 🔴 Toplantı Kaydı | Tarayıcıda yerel kayıt, WebM indirme |
| 🔒 Token Tabanlı Erişim | Katılımcı başına 1 saatlik join token; `peer_id` sunucuda üretilir |

---

## 🏗️ Mimari

```
Tarayıcı (frontend/index.html + static/js/app.js)
  │ 1) POST /api/join-token → token + sunucu üretimli peer_id
  │ 2) WS /ws/{room}/{peer}   (sinyalizasyon, sohbet, durum)
  │ 3) WebRTC P2P             (medya)
  ▼
nginx → FastAPI (backend/main.py, systemd: nexmeet, 127.0.0.1:8009)
  ├─ /api/upload, /api/download, /api/room/{id}/files   → uploads/ (TTL 1 saat)
  ├─ WS /ws/agent/{id}                ← uzak kontrol ajanı (kontrol edilen bilgisayar)
  ├─ WS /ws/control/{oturum}/{peer}   ← kontrol eden tarayıcı
  ├─ /api/control/request|respond|stop
  └─ /api/tts/*  ──HTTP + x-api-key──►  nexmeet-tts (127.0.0.1:5000)
                                         faster-whisper (STT) → çeviri → Kokoro ONNX (TTS), CPU
```

Durum bellekte tutulur (odalar, kontrol oturumları, paylaşılan dosyalar); servis yeniden başladığında sıfırlanır. Ayrıntı: `architect.md`.

---

## 📁 Proje Yapısı

```
nexmeet/
├── backend/
│   ├── main.py              # FastAPI uygulaması — tüm uç noktalar
│   └── requirements.txt
├── frontend/
│   ├── index.html           # Tek sayfa uygulama
│   └── static/
│       ├── css/style.css
│       ├── js/app.js        # WebRTC + arayüz mantığı
│       └── agent/           # Kullanıcıya indirilen ajan kopyası (agent/ ile aynı tutulur)
├── agent/                   # Uzak kontrol ajanı kaynağı
│   ├── agent.py
│   ├── linux_agent.sh
│   └── windows_agent.bat
├── scripts/                 # start.sh / start.bat
├── uploads/                 # Yüklenen dosyalar (geçici)
└── .env.example
```

> `backend/tts/`, `backend/app.js` ve `docker/` eski sürümlerden kalmadır, canlıda kullanılmaz.

---

## ⚙️ Ortam Değişkenleri

`.env.example` dosyasını `.env` olarak kopyalayın:

| Değişken | Açıklama |
|----------|----------|
| `SECRET_KEY` | Gizli anahtar (≥ 32 karakter). Tanımsızsa her başlatmada rastgele üretilir ve token'lar geçersiz olur |
| `ALLOWED_ORIGINS` | CORS için izinli origin'ler (virgülle ayrılmış) |
| `MAX_FILE_SIZE_MB` | Yükleme sınırı (varsayılan 50; nginx `client_max_body_size` ile aynı olmalı) |
| `UPLOADS_DIR` | Yüklenen dosyaların klasörü |
| `HOST`, `PORT` | Dinleme adresi ve portu |
| `TTS_SERVICE_URL` | TTS servisi adresi (boşsa çeviri uçları 503 döner) |
| `TTS_API_KEY` | TTS servisindeki `API_KEY` ile aynı olmalı |

---

## 🚀 Kurulum

```bash
git clone https://github.com/SHapeloglu/nexmeet_v3.git
cd nexmeet_v3
python3 -m venv venv && . venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env        # değerleri doldurun
cd backend && uvicorn main:app --host 127.0.0.1 --port 8000
```

Üretimde uvicorn systemd ile (`WorkingDirectory=…/backend`, `EnvironmentFile=…/.env`) çalıştırılır; nginx TLS sonlandırır ve WebSocket yükseltmesini (`Upgrade`/`Connection`) iletir. Kamera ve mikrofon için HTTPS gerekir (`localhost` hariç).

---

## 📡 API Özeti

| Uç nokta | Açıklama |
|----------|----------|
| `POST /api/join-token` | `{name, room_id}` → `{token, peer_id}` (20/dk). `peer_id` istemciden alınmaz |
| `GET /api/room/{id}/info` | Yalnızca katılımcı sayısı |
| `POST /api/upload/{room_id}` | Dosya yükle (10/dk) |
| `GET /api/download/{file_id}?token=` | Dosya indir (30/dk) |
| `GET /api/room/{id}/files?token=` | Odadaki dosyalar |
| `POST /api/tts/synthesize` | Metni çevir ve seslendir (30/dk) |
| `POST /api/tts/voice-profile`, `GET …/status` | Ses profili (5/dk) |
| `POST /api/control/request\|respond\|stop` | Uzak kontrol izin akışı (hepsi `token` ister) |
| `WS /ws/{room_id}/{peer_id}?token=` | Oda sinyalizasyonu |
| `WS /ws/agent/{agent_id}?session_id=&key=` | Ajan kanalı |
| `WS /ws/control/{session_id}/{peer_id}?token=` | Kontrolcü kanalı |

TTS uçları, TTS servisi hata verirse veya yanıt vermezse `502/504` döner; yapılandırılmamışsa `503`.

---

## 🕹️ Uzak Masaüstü Kontrolü

1. **A**, **B**'ye kontrol isteği gönderir.
2. **B** isteği onaylar. Arayüzde **oturum kodu** ve **ajan anahtarı** gösterilir.
3. **B**, bilgisayarında ajanı başlatır ve bu iki değeri girer:
   - Windows: `windows_agent.bat` · Linux: `linux_agent.sh` (arayüzdeki ajan penceresinden indirilir)
   - ya da: `python agent.py --server wss://<sunucu> --session <oturum> --key <anahtar> --nogui`
4. **A**, B'nin ekranını canlı görür ve fare/klavye ile kontrol eder; her iki taraf da oturumu durdurabilir. Ajan çalışırken fareyi sol üst köşeye götürmek de durdurur (FailSafe).

Ajan gereksinimleri: `pyautogui`, `mss`, `websockets`, `pillow` (Linux'ta ayrıca `python3-xlib`, `python3-tk`, `scrot`).

**Güvenlik:** Ajan anahtarı her oturum için sunucuda üretilir, yalnızca kontrol edilecek tarafa iletilir ve **tek kullanımlıktır**; ajan, hedef onaylamadan bağlanamaz. İzin verilen komutlar: `mouse-move`, `mouse-click`, `mouse-scroll`, `mouse-down`, `mouse-up`, `key-press`, `key-type`, `stop-control`.

---

## 🔒 Güvenlik

- **Token:** `/api/join-token` ile alınır, 1 saat geçerlidir; korumalı uçların hepsi doğrular. Süresi dolan token'lar ve eski kontrol oturumları temizlenir.
- **Kimlik:** `peer_id` sunucuda üretilir; başkası aynı kimlikle bağlanamaz. Odalarda sahip/şifre yoktur: oda kodunu bilen katılabilir.
- **Dosyalar:** yasaklı uzantılar (`.exe .bat .cmd .sh .ps1 .msi .dll .so .dylib .bin .com .scr .vbs .js .jar .py .php .rb`), izinli MIME listesi, 1 saat sonra silme; servis açılırken 1 saatten eski dosyalar da silinir.
- **Hız sınırı:** `slowapi` ile uç noktalara göre (yukarıdaki tablo).
- **CORS:** üretimde `ALLOWED_ORIGINS` ile kısıtlanır.

---

## 🔧 Sorun Giderme

```bash
sudo systemctl status nexmeet          # servis durumu
sudo journalctl -u nexmeet -n 100 --no-pager
curl -s http://127.0.0.1:5000/health   # TTS servisi (varsa)
```

- **Çeviri çalışmıyor (503/502):** `TTS_SERVICE_URL` tanımlı mı, TTS servisi ayakta mı, `TTS_API_KEY` iki tarafta aynı mı?
- **WebSocket kurulamıyor:** nginx'te WebSocket yükseltme başlıkları ve `proxy_read_timeout` kontrol edin.
- **Ajan bağlanamıyor (403):** oturum onaylanmamış, anahtar yanlış ya da anahtar zaten kullanılmış olabilir; yeni bir kontrol isteği başlatın.
- **Dosya 413 hatası:** nginx `client_max_body_size` uygulama sınırından (50 MB) küçük olmasın.

---

## 🗂️ İlgili

TTS servisi ayrı bir projedir (`nexmeet-tts`): faster-whisper tiny + yerel çeviri + Kokoro ONNX, yalnızca CPU.

## 🏷️ Lisans

Bu proje NexMeet ekibine aittir. İzinsiz kullanım ve dağıtım yasaktır.
