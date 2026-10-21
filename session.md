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

## 2026-10-21 — E-posta doğrulamalı üyelik (dal `uyelik`, canlıya alınmadı)

**Yapılanlar:** Giriş yapmayan kullanıcı oda ve ana sayfaya giremiyor (girişe yönlenir). Kayıt (ad soyad, e-posta, parola), 24 saatlik tek kullanımlık e-posta doğrulama, 30 gün sabit oturum çerezi, parola sıfırlama (1 saat), çıkış, hesap silme eklendi. `join-token` yalnız doğrulanmış oturuma verilir ve adı hesaptan alır. Veritabanı MySQL (PyMySQL), parolalar argon2. Testler (45 adet) tek kullanımlık `mysql:8.0` konteynerinde geçti; yerelde uvicorn 127.0.0.1:18009 üzerinde curl ile kayıt→doğrulama→giriş→join-token→çıkış akışı çalıştırıldı.

**Kararlar / neden:** Kayıt ve sıfırlama yanıtı kayıtlı olup olmadığını göstermez; mail arka planda gönderilir (zamanlama sızıntısı azalır). Sıfırlama, e-posta sahipliğini kanıtladığı için hesabı doğrulanmış sayar. Kayıtlı e-postaya yapılan kayıt sessizce yok sayılır (parola değiştirilemez). Giriş ucu `yonlendirme` değerini sunucuda doğrular.

**Açık sorunlar:** Canlı veritabanı ve SMTP ayarları yok; canlıya dağıtım yapılmadı. Hesap silme için arayüz yok (yalnız uç). Tarayıcıda (gerçek kamera/mikrofon ve düğmeler) elle test edilmedi. Parolasız oturum düşürme ve IP başına hız sınırı, nginx arkasında `X-Forwarded-For` ile doğru IP'ye dayanır (uvicorn varsayılanı).

**Sıradaki adım:** Canlı DB kullanıcısı ve SMTP kurulumu; tarayıcı testi; dağıtım kararı.

