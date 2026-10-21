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
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Üyelik veritabanı (MySQL). Varsayılan port 3306, ad `nexmeet`. Bağlanılamazsa üyelik uçları 503 döner, toplantı çalışmaya devam eder |
| `PUBLIC_BASE_URL` | Doğrulama ve sıfırlama bağlantılarının kök adresi (örn. `https://nexmeet.powerbiegitimi.com`). Origin kontrolünde de kullanılır |
| `MAIL_BACKEND` | `smtp` (varsayılan) veya `dosya` (test: mail göndermez, `MAIL_DIR` klasörüne `.txt` yazar) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | SMTP ayarları (STARTTLS, varsayılan port 587) |
| `FORWARDED_ALLOW_IPS` | Nginx/Docker arkasında `*` olmalı; yoksa tüm kullanıcılar tek IP sayılır ve hız sınırları ortak olur |
| `MAIL_DIR` | `MAIL_BACKEND=dosya` iken mail çıktılarının klasörü (varsayılan `mail_kutusu/`) |

---

## 👤 Üyelik ve Giriş

Toplantılara yalnız üyeler katılabilir. Oda sayfasına giriş yapmamış kullanıcı giriş sayfasına yönlendirilir ve giriş sonrası aynı odaya döner.

- **Kayıt:** ad soyad (2–50 karakter), e-posta, parola (10–128 karakter). Doğrulama bağlantısı 24 saat geçerlidir ve tek kullanımlıktır. Doğrulanmadan giriş yapılamaz.
- **Oturum:** 30 gün sabit süreli, `HttpOnly`, `Secure`, `SameSite=Lax` çerez. Çıkış oturumu veritabanından siler.
- **Parola sıfırlama:** 1 saat geçerli, tek kullanımlık bağlantı. Sıfırlama tüm oturumları kapatır.
- **Hesap silme:** parola istenir; hesap ve oturumları silinir.
- **Koruma:** parolalar argon2 ile hash'lenir; token'lar veritabanında yalnız SHA-256 özeti olarak tutulur. 10 hatalı girişten sonra hesap 15 dakika kilitlenir. Kayıt, giriş ve mail uçlarında IP başına hız sınırı ve e-posta başına günlük mail kotası (5) vardır. Kayıt ve parola sıfırlama yanıtları, e-posta kayıtlı olup olmadığını belli etmez.

### Kurulum adımları (üyelik)

```bash
# 1) MySQL'de veritabanı ve kullanıcı (tablolar uygulama açılışında oluşturulur)
#    CREATE DATABASE nexmeet CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
# 2) .env içinde DB_*, PUBLIC_BASE_URL ve SMTP_* değerlerini doldurun (.env.example'a bakın)
# 3) Bağımlılıklar (PyMySQL, argon2-cffi dahil)
pip install -r backend/requirements.txt
# 4) Sağlık kontrolü: {"durum":"tamam","db":"tamam"} dönmeli
curl -s http://127.0.0.1:8000/api/saglik
```

Testler gerçek bir MySQL gerektirir (tek kullanımlık konteyner önerilir; ortak sunucu kullanılmamalı):

```bash
docker run -d --rm --name nexmeet-test-mysql -e MYSQL_ROOT_PASSWORD=<rastgele> \
  -e MYSQL_DATABASE=nexmeet -p 127.0.0.1:33999:3306 --memory 512m mysql:8.0
python3 -m venv .venv-test && .venv-test/bin/pip install -r backend/requirements.txt -r tests/requirements.txt
TEST_DB_PASSWORD=<rastgele> .venv-test/bin/pytest tests -q
docker stop nexmeet-test-mysql
```

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
| `POST /api/join-token` | `{room_id}` → `{token, peer_id}` (20/dk). Yalnız giriş yapmış ve doğrulanmış kullanıcı; ad hesaptan gelir |
| `POST /api/auth/kayit` | `{ad_soyad, eposta, parola}` → her durumda aynı yanıt (5/saat) |
| `POST /api/auth/dogrula` | `{token}` → e-posta doğrulama |
| `POST /api/auth/dogrulama-tekrar` | `{eposta}` → doğrulama mailini yeniden gönder (3/saat) |
| `POST /api/auth/giris` | `{eposta, parola, yonlendirme}` → oturum çerezi (10/dk) |
| `GET /api/ben` | Oturumdaki kullanıcı |
| `POST /api/auth/cikis` | Oturumu sonlandırır |
| `POST /api/auth/sifre-unuttum` | `{eposta}` → sıfırlama bağlantısı (3/saat) |
| `POST /api/auth/sifre-sifirla` | `{token, parola}` → yeni parola, tüm oturumları kapatır |
| `POST /api/auth/hesabi-sil` | `{parola}` → hesabı ve oturumları siler |
| `GET /api/saglik` | Servis ve veritabanı durumu |
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
