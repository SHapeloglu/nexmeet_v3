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

## 2026-11-08 — 2026-11-09 — Canlı sunucu denetimi, dağıtım ve repo senkronu

**Yapılanlar:**
- Sunucu (Contabo) salt okunur incelendi. Canlı kurulum Docker Compose (`/opt/nexmeet`); eski systemd birimleri disabled/inactive idi.
- Canlı kod repoya alındı (PR #6). Docker imajında dosya indirme güvenlik başlıkları (`Content-Security-Policy: sandbox`, `nosniff`) yoktu; yeni imaj `nexmeet:2026-11-08` ile dağıtıldı. Eski imaj `nexmeet:rollback-2026-10-21` olarak saklandı.
- Eski systemd birimleri ve `/root/nexmeet`, `/root/nexmeet-tts` yedek alınıp (`/root/backups/`) kaldırıldı.
- Repo: `docker/` canlı kurulumla hizalandı (PR #3), `docker/backend/` kaldırıldı (PR #4), TTS kaynağı `tts-service/` altına eklendi (PR #5), TURN sabitleri ve `backend/tts/`, `backend/app.js` kaldırıldı (PR #7).
- TTS API anahtarı 48 karakterden 64 hex karaktere yenilendi; yanlış anahtar 401, yeni anahtar 200.

**Kararlar / neden:**
- Güvenlik düzeltmesi için yeni imaj eski imajın yanında etiketlendi; geri dönüş tek komutla mümkün.
- TURN sunucusu yok ve 3478 dinlenmiyor; sabit kimlik bilgisi kaldırıldı, yalnız STUN kaldı.
- Dağıtım sırasında TTS anahtarı, konteynerler durdurulmuş halde yeniden oluşturularak değiştirildi; AutoSleep'in `docker start`'ı yeni ortam değişkenlerini kullanır.
- Git geçmişi yeniden yazılmadı: özgeçmiş verisi ve eski TURN parolası geçmişte duruyor. Public repo için ayrı onay gerekiyor.

**Açık sorunlar:**
- SMTP ile gerçek mail gönderimi test edilmedi.
- PR #2 (`hesap-sil`) incelemede; `auth.py` değiştiriyor.
- Testler (`tests/`) MySQL gerektiriyor, çalıştırılmadı.
- Konteynerler şu an açık; AutoSleep boşta kalınca durduracak.

**Sıradaki adım:** PR #2 incelemesi sonucuna göre birleştirme; SMTP testi; git geçmişi temizliği için onay.

## 2026-11-09 — Kontrol, test ve dağıtım (17:00'a kadar devralındı)

**Yapılanlar:**
- PR #2 (hesap silme) birleşti (`649414b`). İnceleme bulguları düzeltildi: `/hesabim` yönlendirmesi, silinen hesabın join token'larının iptali, endpoint'e oran sınırı, `mail_log` temizliği.
- `main` testleri çalıştırıldı: geçici `mysql:8.0` konteyneri (`127.0.0.1:33999`, sunucuda), 47 test geçti. Konteyner, kopya dizin ve parola dosyası işlem sonunda silindi.
- Canlı imaj `main`'den yeniden üretildi (`nexmeet:2026-11-09`, `4a7d826f3426`). İçerikte CSP başlığı, hesap silme ucu, `hesabim.html` var; TURN kimlik bilgisi yok.
- Dağıtım: `nexmeet:latest` yeni imaja geçti. Önceki imaj `nexmeet:rollback-2026-11-08` olarak saklandı; `nexmeet:rollback-2026-10-21` duruyor.
- Duman testi (konteyner ayağa kalktıktan sonra): `/giris` 200, `/` ve `/hesabim` oturumsuz yönlendirme, `/api/ben` ve hesap silme 401, dış HTTPS `/giris` 200.
- SMTP sunucusuna bağlantı, STARTTLS ve AUTH teklifi doğrulandı; mail gönderilmedi.

**Kararlar / neden:**
- Dağıtım, daha önce onaylanan güvenlik düzeltmesinin üzerine main'in test edilmiş sürümünü eklemek için yapıldı; hesap silme ve TURN kaldırma canlıya gelsin diye. Eski imaj geri dönüş için saklı.
- Git geçmişi yeniden yazılmadı: özgeçmiş verisi ve eski TURN parolası hâlâ geçmişte. Force-push, public repo için açık onay gerektiriyor.

**Açık sorunlar:**
- Kayıt/parola sıfırlama mailinin gerçekten ulaştığı denenmedi.
- Tarayıcıda hesap silme ve giriş akışı elle denenmedi.
- Git geçmişi temizliği onay bekliyor.
- Konteynerler şu an durmuş (AutoSleep); smoke testten sonra uyku moduna geçti.

**Sıradaki adım:** Git geçmişi temizliği için karar; gerçek mail akışının elle denenmesi.

**Ek kontrol (aynı gün, ikinci tur):**
- `task.md` notu eski TURN parolasını düz metin olarak yeniden yazmıştı; PR #10 ile kaldırıldı. Ağaçta parola yok; yalnız git geçmişinde duruyor (geçmiş temizliği hâlâ onay bekliyor).
- TTS kaynağı `tts-service/` altına taşındığı hâlde CLAUDE.md, README.md, architect.md ve `docker/docker-compose.yml` "repoda yok" diyordu; düzeltildi.
- Yerel git deposunda kesinti sırasında 3 sıfır baytlık nesne dosyası ve bozuk bir uzak-izleme referansı oluştu. Dosyalarda veri yoktu; silinip uzaktan yeniden çekildi, `git fsck` temiz. Uzaktaki depo etkilenmedi.
- Sunucu denetimi temiz: artık dizin/test konteyneri yok, iki yedek `gzip -t` ile sağlam, TTS anahtarı iki env'de eşleşiyor, env izinleri 600, nginx geçerli, sertifika 2027-01-04'e kadar geçerli.



## 2026-11-09 — Git geçmişi temizliği

**Yapılanlar:**
- Kullanıcı onayıyla geçmiş yeniden yazıldı: `uploads/` (özgeçmiş PDF ve JPG), eski TURN parolası ve iki eski public IP tüm dallardan kaldırıldı.
- Yedek: ayna klon `~/nexmeet-backup-20261109-2321-mirror.git` (eski geçmişi içerir; yalnızca yerelde).
- 11 dal zorla yüklendi. Commit sayısı 47 korundu. PR ref'leri (`refs/pull/*`) GitHub tarafından yönetildiği için yüklenmedi.
- Yerel `main` ve uzak `origin/main` aynı SHA'da.

**Açık / bilinen:**
- Yerel çalışma ortamının `refs/t3/orchestration-v2/*` kontrol noktaları eski geçmişe işaret ediyor. Uzağa hiç gönderilmedi; araç kendi yönettiği için silinmedi.
- Commit yazarı e-postaları metadata olarak kalır (kişisel veri içeriği temizlendi, yazar bilgisi değil).
- GitHub'ın önbelleğindeki eski görünümler için destek talebi gerekebilir.
