# task.md — NexMeet (v3) Görevleri

## 🔜 Sıradaki

- [x] 2026-10-18 ✅ ~~**Uzak kontrol bozuk**~~ — kök neden: `/ws/{room_id}/{peer_id}` rotası `/ws/agent/{id}`'yi gölgeliyordu (ajan rotası öne alındı); ayrıca ajan artık oturuma özel tek kullanımlık `agent_key` ile bağlanıyor (hedef onayladıktan sonra, yalnız hedefe iletilir, arayüzde gösterilir); `.bat`/`.sh`/GUI `--key` alıyor, indirilen kopya `agent/` ile eşitlendi. Uçtan uca denendi (geçici portta). Commit edilmedi. (#64)
- [x] 2026-10-16 ✅ ~~**Çeviri bozuk**~~ — yerel Argos modeline geçildi (`/root/nexmeet-tts`). Eski not: `nexmeet-tts` GoogleTranslator → sunucu IP'si Google captcha'sında, `TooManyRequests`. Resmi API ya da yerel çeviri modeli. (#64)
- [ ] 🟠 TTS proxy uçları (`tts_synthesize`, `tts_voice_profile*`) TTS hatasında `response.json()` ile çöküyor → durum kodunu kontrol et, anlamlı hata dön, ön yüzde kullanıcıya göster.
- [x] 2026-10-18 ✅ ~~`/api/control/stop` 401~~ — `app.js` iki çağrıya `token` eklendi (stop 200 döndü).
- [ ] 🟠 peer_id istemciden geliyor ve aynı peer_id için yeniden token alınabiliyor → kimlik taklidi / uzak kontrol onayı sahteciliği. peer_id'yi sunucu üretsin; `/api/room/{id}/info` token istesin.
- [ ] 🟡 nginx `client_max_body_size 50M` ↔ `MAX_FILE_SIZE_MB=100` uyumsuz; birini seç (50 MB öneri, dosya belleğe okunuyor).
- [ ] 🟡 Başlangıçta `uploads/`'taki 1 saatten eski dosyaları sil (yeniden başlatma/AutoSleep sonrası yetim dosyalar).
- [ ] 🟡 WS genel hata yolunda `peer-left` yayınla; `control_sessions`/`join_tokens` için periyodik temizlik; `control_endpoint`'te token peer_id = kontrolcü kontrolü.

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
