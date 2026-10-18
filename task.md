# task.md — NexMeet (v3) Görevleri

## 🔜 Sıradaki

- [x] 2026-10-18 ✅ ~~**Uzak kontrol bozuk**~~ — kök neden: `/ws/{room_id}/{peer_id}` rotası `/ws/agent/{id}`'yi gölgeliyordu (ajan rotası öne alındı); ayrıca ajan artık oturuma özel tek kullanımlık `agent_key` ile bağlanıyor (hedef onayladıktan sonra, yalnız hedefe iletilir, arayüzde gösterilir); `.bat`/`.sh`/GUI `--key` alıyor, indirilen kopya `agent/` ile eşitlendi. Uçtan uca denendi (geçici portta). Commit edilmedi. (#64)
- [x] 2026-10-16 ✅ ~~**Çeviri bozuk**~~ — yerel Argos modeline geçildi (`/root/nexmeet-tts`). Eski not: `nexmeet-tts` GoogleTranslator → sunucu IP'si Google captcha'sında, `TooManyRequests`. Resmi API ya da yerel çeviri modeli. (#64)
- [x] 2026-10-18 ✅ ~~TTS proxy hata yönetimi~~ — ortak `_tts_istek`: 502/503/504 + ön yüzde toast.
- [x] 2026-10-18 ✅ ~~`/api/control/stop` 401~~ — `app.js` iki çağrıya `token` eklendi (stop 200 döndü).
- [x] 2026-10-18 ✅ ~~peer_id taklidi~~ — `/api/join-token` peer_id'yi sunucuda üretir; `/api/room/{id}/info` yalnız sayı döner. (Oda sahibi/şifresi hâlâ yok: odayı bilen katılabilir.)
- [x] 2026-10-18 ✅ ~~Dosya sınırı~~ — `MAX_FILE_SIZE_MB` 50'ye çekildi (kod varsayılanı, `.env.example`, canlı `.env`).
- [x] 2026-10-18 ✅ ~~Yetim dosyalar~~ — başlangıçta 1 saatten eski `uploads/` dosyaları silinir. ⚠ Repoda izlenen 2 eski kullanıcı dosyası (Haziran) ilk başlatmada silinecek (git'ten geri alınabilir).
- [x] 2026-10-18 ✅ ~~Küçükler~~ — WS genel hata yolunda `peer-left` yayınlanır; eski kontrol oturumları ve token'lar `cleanup_expired_tokens` ile temizlenir (`created_at`, 1 saat); `control_endpoint` token peer_id'sini kontrolcüyle karşılaştırır.

- [ ] **README güncel değil** — 2026-07-20 değişiklikleri yok: agent token doğrulaması, yüklenen dosyaların otomatik silinmesi (`FILE_TTL_SECONDS`, `auto_delete_file`) ve TTS metin desteği README'de anlatılmıyor. (`/root/ISLISTESI.md` Aktif #17)
- [ ] Public repodan izlenen kullanıcı dosyalarını çıkar: `git rm --cached uploads/*` (içerik kontrolü + kullanıcı onayı; geçmiş temizliği ayrıca)
- [ ] README'yi canlı mimariye göre güncelle (Contabo, `nexmeet.powerbiegitimi.com`, Kokoro CPU, ses klonlama yok) ve **IP adreslerini çıkar**
- [ ] Kullanılmayan kodu temizle: `backend/tts/`, `backend/app.js`, `docker/backend/` (veya Docker'ı güncelle), `backend/__pycache__`
- [ ] `nexmeet-tts.service` içindeki zayıf `API_KEY`'i güçlü bir değerle değiştir ve backend `.env` `TTS_API_KEY` ile eşle (unit yerine `EnvironmentFile`)

## 🚧 Devam Eden

_(şu anda boş)_

## ✅ Tamamlanan

- [x] 2026-10-05 — Çalışma dosyaları kod ve canlı servisler incelenerek yeniden yazıldı
- [x] 2026-07-20 — Ajan token doğrulaması, dosyaların otomatik silinmesi, TTS'e doğrudan metin desteği
- [x] 2026-06-25 — Backend + TTS proxy, uzak kontrol ajanı
