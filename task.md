# task.md — NexMeet (v3) Görevleri

## 🔜 Sıradaki

- [ ] 🟠 **Ajan kopyaları ayrışmış:** `frontend/static/agent/agent.py` (indirilen kopya: `--key-file`, `NEXMEET_AGENT_KEY`, anahtar maskeleme) `agent/agent.py` kaynağından yeni; kaynak bu sürüme getirilmeli. 2026-10-18'deki "eşitlendi" notu artık geçerli değil.
- [ ] 🟠 **Eski TURN alan adı geçmişte:** `TURN_URLS = 'turn:nexmeet.powerbi.com.tr:3478'` satırı eski commit'lerde duruyor. Parola ve IP'ler temizlendi, alan adı temizlenmedi. Karar bekliyor: geçmiş yeniden yazılıp zorla yüklensin mi?
- [ ] 🟡 **Kökteki `start.bat` eski kopya:** kişisel Windows yolu (`C:\Users\yeliz\...`) içeriyor ve `scripts/start.bat` ile ayrışmış. Silinmesi karar bekliyor.
- [ ] 🟠 **Üyelik canlı, gerçek mail gönderimi test edilmedi:** veritabanı bağlantısı canlı (`mysql-ortak:3306/nexmeet`). SMTP sunucusuna bağlantı, STARTTLS ve AUTH teklifi doğrulandı (2026-11-09, mail gönderilmedi). Kayıt/parola sıfırlama mailinin gerçekten ulaştığı tarayıcı/mail kutusunda henüz denenmedi.
- [x] 2026-11-09 ✅ ~~**Git geçmişinde kişisel veri ve eski TURN parolası**~~ — `uploads/` (özgeçmiş PDF/JPG), eski TURN parolası ve eski public IP'ler tüm dallardan çıkarıldı; `git filter-repo` ile yeniden yazıldı ve zorla yüklendi. Yedek: yerelde ayna klon (`~/nexmeet-backup-20261109-2321-mirror.git`).
- [x] 2026-11-09 ✅ ~~**TURN fiilen yok**~~ — sabit kullanıcı/şifre `app.js`'ten kaldırıldı (PR #7); yalnız STUN kullanılıyor. Coturn kurulumu `backlog.md`'de.

- [x] 2026-10-18 ✅ ~~**Uzak kontrol bozuk**~~ — kök neden: `/ws/{room_id}/{peer_id}` rotası `/ws/agent/{id}`'yi gölgeliyordu (ajan rotası öne alındı); ayrıca ajan artık oturuma özel tek kullanımlık `agent_key` ile bağlanıyor (hedef onayladıktan sonra, yalnız hedefe iletilir, arayüzde gösterilir); `.bat`/`.sh`/GUI `--key` alıyor, Uçtan uca denendi (geçici portta). Kod sonradan repoya alındı (PR #6). (#64)
- [x] 2026-10-16 ✅ ~~**Çeviri bozuk**~~ — yerel Argos modeline geçildi (`/root/nexmeet-tts`). Eski not: `nexmeet-tts` GoogleTranslator → sunucu IP'si Google captcha'sında, `TooManyRequests`. Resmi API ya da yerel çeviri modeli. (#64)
- [x] 2026-10-18 ✅ ~~TTS proxy hata yönetimi~~ — ortak `_tts_istek`: 502/503/504 + ön yüzde toast.
- [x] 2026-10-18 ✅ ~~`/api/control/stop` 401~~ — `app.js` iki çağrıya `token` eklendi (stop 200 döndü).
- [x] 2026-10-18 ✅ ~~peer_id taklidi~~ — `/api/join-token` peer_id'yi sunucuda üretir; `/api/room/{id}/info` yalnız sayı döner. (Oda sahibi/şifresi hâlâ yok: odayı bilen katılabilir.)
- [x] 2026-10-18 ✅ ~~Dosya sınırı~~ — `MAX_FILE_SIZE_MB` 50'ye çekildi (kod varsayılanı, `.env.example`, canlı `.env`).
- [x] 2026-10-18 ✅ ~~Yetim dosyalar~~ — başlangıçta 1 saatten eski `uploads/` dosyaları silinir. Repoda izlenen 2 eski kullanıcı dosyası 2026-11-09'da git'ten de çıkarıldı.
- [x] 2026-10-18 ✅ ~~Küçükler~~ — WS genel hata yolunda `peer-left` yayınlanır; eski kontrol oturumları ve token'lar `cleanup_expired_tokens` ile temizlenir (`created_at`, 1 saat); `control_endpoint` token peer_id'sini kontrolcüyle karşılaştırır.

- [x] 2026-10-18 ✅ ~~README güncel değil~~ — yukarıdakiyle kapandı.
- [x] 2026-10-18 ✅ ~~Public repodan `uploads/` dosyaları çıkarıldı~~ (`git rm --cached`). Git geçmişinden de çıkarıldı (2026-11-09, yukarıdaki kayıt).
- [x] 2026-10-18 ✅ ~~README yeniden yazıldı~~ (canlı mimari, IP'ler çıkarıldı, ajan anahtarı, 50 MB, TTL); `requirements.txt`'e eksik `slowapi`/`httpx`/`python-dotenv` eklendi.
- [x] 2026-11-09 ✅ ~~Kullanılmayan kodu temizle~~ — `backend/tts/` ve `backend/app.js` PR #7 ile silindi; `docker/backend/` PR #4 ile silindi.
- [x] 2026-11-09 ✅ ~~Sunucudaki TTS API anahtarı zayıf~~ — 64 hex anahtar üretildi; `nexmeet.env` ve `tts.env` eşleşiyor. Yanlış anahtar 401, yeni anahtar 200 döndü. Eski env yedekleri silindi.

## 🚀 Dağıtım — Açık İşler

Canlı dağıtım Docker Compose (`/opt/nexmeet`); repo ile sunucu arasındaki farklar burada takip edilir.

- [x] (a) Sunucu kodu GitHub'a alındı (PR #6) ve güvenlik düzeltmeleriyle yeniden dağıtıldı (`nexmeet:2026-11-08`, eski imaj `nexmeet:rollback-2026-10-21`)
- [x] (b) TTS servisi kaynağı repoya eklendi (PR #5, `tts-service/`)
- [x] (c) Üyelik veritabanı bağlantısı doğrulandı (konteyner logu); SMTP açık, yukarıya bkz.
- [x] (d) Eski systemd birimleri kaldırıldı: `nexmeet.service`, `nexmeet-tts.service`, `/root/nexmeet` (yedek sunucuda)

## 🚧 Devam Eden


## ✅ Tamamlanan

- [x] 2026-11-11 — `architect.md`, `README.md`, `CLAUDE.md`, `backlog.md`, `task.md` ve `session.md` kodla karşılaştırılıp güncellendi (üyelik katmanı, Argos çeviri, yalnız STUN, ajan anahtarı, test komutu, `uploads/` durumu). PR #12 (`docs/gecmis-temizligi`) ile birleştirildi.

- [x] 2026-11-09 — Hesap silme (PR #2) birleşti; 47 test (`tests/`) geçti (geçici MySQL konteyneri, sunucuda, işlem sonrası silindi). Main sürümü `nexmeet:2026-11-09` olarak dağıtıldı; önceki imaj `nexmeet:rollback-2026-11-08`. TURN kimlik bilgisi ve hesap silme artık canlıda.
- [x] 2026-11-09 — Sunucu kodu repoya alındı (PR #6); docs, temizlik, TTS kaynağı ve TURN düzeltmesi PR #3, #4, #5, #7 ile birleşti. Canlı TTS anahtarı yenilendi; eski systemd birimleri ve `/root/nexmeet`, `/root/nexmeet-tts` yedek alınıp kaldırıldı (yedekler `/root/backups/`).

- [x] 2026-10-21 — E-posta doğrulamalı üyelik: kayıt, doğrulama, oturum (30 gün), parola sıfırlama, hesap silme, join-token'ın hesaptan ad alması; 45 test geçti (`tests/`). Commit edildi, push/dağıtım yok.
- [x] 2026-10-05 — Çalışma dosyaları kod ve canlı servisler incelenerek yeniden yazıldı
- [x] 2026-07-20 — Ajan token doğrulaması, dosyaların otomatik silinmesi, TTS'e doğrudan metin desteği
- [x] 2026-06-25 — Backend + TTS proxy, uzak kontrol ajanı
