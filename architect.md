# architect.md — NexMeet (v3) Mimarisi

```
Tarayıcı (frontend/*.html + static/js/app.js, auth.js, hesabim.js)
  │ 0) Üyelik: /api/auth/* → oturum çerezi (30 gün); toplantı için zorunlu
  │ 1) POST /api/join-token → 1 saatlik token + sunucu üretimli peer_id
  │ 2) WS /ws/{room}/{peer}  (sinyalizasyon, chat, durum)
  │ 3) WebRTC P2P (medya; yalnız STUN — TURN yok)
  ▼
nginx (nexmeet.powerbiegitimi.com) → FastAPI backend/main.py + auth.py (Docker konteyneri nexmeet, 127.0.0.1:8009)
  ├─ /api/upload/{room}, /api/download/{file_id}?token, /api/room/{room}/files  → uploads/ (TTL 1 saat)
  ├─ WS /ws/agent/{agent_id}?session_id&key      ← uzak kontrol ajanı (agent.py, kontrol edilen PC)
  ├─ WS /ws/control/{session}/{controller_peer}  ← kontrol eden tarayıcı
  ├─ /api/control/request|respond|stop           ← izin akışı
  ├─ /api/auth/*, /giris, /kayit, /hesabim …     → MySQL (db.py, veritabanı nexmeet) + SMTP (mailer.py)
  └─ /api/tts/synthesize, /api/tts/voice-profile[/status] ──HTTP X-API-Key──► nexmeet-tts (Docker konteyneri)
                                                                               faster-whisper tiny (STT, CPU)
                                                                               → Argos Translate (TR→EN, yerel CTranslate2)
                                                                               → Kokoro ONNX (TTS, af_heart)
```

## Backend

- **`backend/main.py`:** oda, sinyalizasyon, dosya paylaşımı, uzak kontrol ve TTS proxy uçları.
- **`backend/auth.py`:** üyelik. Kayıt, e-posta doğrulama, giriş, parola sıfırlama, çıkış, hesap silme ve sayfa yönlendirmeleri. Oturum ve tek kullanımlık token'lar veritabanında tutulur; token'ların yalnız SHA-256 özeti saklanır. Parolalar argon2 ile hash'lenir. Girişte 10 hatalı denemeden sonra hesap 15 dakika kilitlenir.
- **`backend/db.py`:** MySQL bağlantısı (PyMySQL). Tablolar uygulama açılışında oluşturulur. Veritabanına bağlanılamazsa üyelik uçları 503 döner, toplantılar çalışmaya devam eder.
- **`backend/mailer.py`:** doğrulama ve sıfırlama postaları. `MAIL_BACKEND=smtp` (STARTTLS) ya da test için `dosya`.
- **Durum bellekte:** odalar, peer'lar, paylaşılan dosyalar, kontrol oturumları. Tek süreç; yeniden başlatmada sıfırlanır.
- **Join token:** `generate_join_token` / `validate_join_token`. `secrets.token_urlsafe` ile rastgele üretilir, bellekte tutulur, 1 saat geçerlidir ve `user_id` saklar. `SECRET_KEY` kullanılmaz. Süresi dolanlar `cleanup_expired_tokens` ile temizlenir. Bir hesap silinince o kullanıcının token'ları da düşer.
- **Join token'ı yalnız doğrulanmış oturum alır;** görünen ad hesaptan gelir, istemciden alınan ad yok sayılır.
- **Dosya:** `validate_file` (uzantı, MIME, boyut en fazla 50 MB), `auto_delete_file` (`FILE_TTL_SECONDS = 3600`). Servis açılırken 1 saatten eski dosyalar da silinir.
- **Güvenlik katmanları:** `slowapi` ile uç noktalara göre hız sınırı; CORS `ALLOWED_ORIGINS` ile; üyelik uçlarında `origin_kontrol`.

## Uzak Kontrol

Kontrol edilecek bilgisayarda `agent.py` (Windows `.bat` / Linux `.sh` başlatıcılarıyla) çalışır ve backend'e WebSocket ile bağlanır.

1. Kontrol eden katılımcı istek gönderir; karşı taraf onaylar.
2. Onaydan sonra sunucu oturuma özel, **tek kullanımlık** bir ajan anahtarı üretir. Anahtar yalnız hedefe iletilir ve arayüzde gösterilir.
3. Ajan bu anahtarla bağlanır. Sunucu anahtarı ilk kabulde siler; ikinci bağlantı reddedilir.
4. Fare ve klavye olayları backend üzerinden ajana iletilir. Her iki taraf oturumu durdurabilir.

Ajan iki yerde bulunur: `agent/` (kaynak) ve `frontend/static/agent/` (kullanıcıya indirilen kopya). Ajan değiştiğinde iki yer birlikte güncellenmelidir.

## Dağıtım

- **Canlı yol Docker Compose;** compose dizini sunucuda `/opt/nexmeet` (repo dışı).
- **Konteyner `nexmeet`:** uvicorn, `127.0.0.1:8009`, ortam `nexmeet.env`, yüklemeler için `./uploads` volume, `restart unless-stopped`. İmaj `python:3.12-slim` üzerine kurulur; repodaki karşılığı `docker/Dockerfile` ve `docker/docker-compose.yml`dir. Etiketler: `nexmeet:latest` (güncel), `nexmeet:2026-11-09` (güncel sürüm), `rollback-*` (geri dönüş için önceki imajlar).
- **Konteyner `nexmeet-tts`:** Kokoro ONNX TTS, ortam `tts.env`, `restart unless-stopped`. Kaynağı repoda: `tts-service/` (`Dockerfile.tts`, `main.py`). Model dosyaları repoda değildir.
- **Ağlar:** `nexmeet` (dahili) ve dış `ortak-db` (üyelik veritabanı `mysql-ortak`).
- **Otomatik uyku (AutoSleep):** sunucuda çalışır; uygulamanın dışındadır.
- **Eski systemd birimleri** (`nexmeet.service`, `nexmeet-tts.service`) ve `/root/nexmeet`, `/root/nexmeet-tts` kaldırıldı (yedek sunucuda `/root/backups/`).

## Mimari Kararlar

- **P2P medya, sunucu yalnız sinyalizasyon:** sunucu maliyeti düşük; çok katılımcıda tarayıcı yükü artar (SFU yok).
- **Çeviri ayrı servis:** ağır modeller backend'i bloklamasın. v2'de GPU EC2 + ses klonlama planlandı; v3'te maliyet için CPU Kokoro'ya inildi.
- **Çeviri yerel (Argos):** Google çeviri, sunucu IP'sini engelleyince (2026-10-16) yerel Argos modeline geçildi.
- **TURN yok, yalnız STUN:** sabit TURN kimlik bilgisi 2026-11-09'da kaldırıldı. Simetrik NAT arkasındaki kullanıcılar bağlanamayabilir; coturn `backlog.md`'de.
- **Bellekte durum:** basitlik; yatay ölçekleme yok.
