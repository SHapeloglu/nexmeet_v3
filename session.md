# session.md — NexMeet (v3) Oturum Günlüğü

---

## 2026-10-05

- Şablondan üretilmiş çalışma dosyaları kod ve canlı servisler incelenerek yeniden yazıldı.
- Tespitler: README EC2/GPU mimarisini ve IP'leri anlatıyor (repo public); canlı sistem Contabo'da, Kokoro CPU; `uploads/` içinde 2 kullanıcı dosyası izleniyor; `backend/tts`, `backend/app.js`, `docker/` kalıntı.

---

## Önceki Çalışmalar (git geçmişinden)

- **2026-07-20** — Ajan token doğrulama, otomatik dosya silme, TTS text desteği.
- **2026-06-25** — Backend initial commit + yüklemeler (v2 ile aynı temel).
- **2026-05-14** — İlk commit (v1 temeli).

---

### Kayıt Şablonu

```markdown
## YYYY-AA-GG
**Yapılanlar:** ...
**Kararlar / neden:** ...
**Açık sorunlar:** ...
**Sıradaki adım:** ...
```

## 2026-10-16 — Hata incelemesi (kod okuma + canlı deneme)

- Uzak kontrol: indirilen ajan `/ws/agent`'a parametresiz bağlanıyor → 403 (canlıda denendi). Çeviri: Google IP'yi captcha'ya düşürmüş, `TooManyRequests`; backend TTS hatasında `response.json()` ile 500. `/api/control/stop` ön yüzden tokensiz → 401. peer_id taklidi mümkün. nginx 50M ↔ uygulama 100 MB. Ayrıntı `task.md` ve `/root/topluisler.md` #64. Kod değiştirilmedi.
- AutoSleep 20 dk'ya indirildi; toplantı sürerken açık WebSocket olduğu için uyutmuyor (kontrol edildi).
