# task.md — NexMeet (v3) Görevleri

## 🔜 Sıradaki

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
