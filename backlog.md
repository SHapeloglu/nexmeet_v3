# backlog.md — NexMeet Fikir Havuzu

- SFU (mediasoup / LiveKit) — 4+ katılımcıda P2P mesh yükünü azaltmak için.
- TURN sunucusu (coturn) kurulumu ve ICE yapılandırmasının .env'den gelmesi. Şu an yalnız STUN var; simetrik NAT arkasındaki kullanıcılar bağlanamayabilir.
- Ses klonlama: Kokoro yerine klonlama destekli model (GPU gerektirir) — maliyet/fayda değerlendirmesi.
- Çeviri hedef dillerini genişletme (şu an TR→EN, yerel Argos modeli; Kokoro sesleri dil başına).
- Oda/sohbet durumunu Redis'e taşıyıp çoklu worker desteği.
- Bekleme odası / host onayı, oda şifresi.
- Sunucu tarafı kayıt.
- Hesabım: oturum açıkken parola değiştirme (şu an yalnız parola sıfırlama ve hesap silme var).
- Testleri CI'da (ör. GitHub Actions, geçici MySQL konteyneriyle) otomatik çalıştırma.

## Kayıtlı açık işler

### B1: Hesap kilidi IP'den bağımsız
- **Kategori:** teknik borç / güvenlik
- **Neden:** kilit hesap bazlı; bir hesaba art arda hatalı giriş yapılarak o hesap 15 dakika kilitlenebilir (hedefli hizmet reddi).
- **Notlar:** kilidi IP + hesap ile sınırlamak yeni şema gerektirir. KARAR: şu an kabul edilmiş risk. Kaynak: `backend/auth.py` (`_basarisiz_giris`, `_giris_islem`).

### B4: Mail kotası yarışı
- **Kategori:** teknik borç
- **Neden:** kota kontrolü (`_mail_kotasi_var`) ile kayıt (`mail_log`) arasında bekleme var; kayıt yalnız başarılı gönderimden sonra yazıldığı için eşzamanlı isteklerde kota aşılabilir (en fazla 5+N-1, N eşzamanlı istek).
- **Notlar:** tam çözüm gönderimden önce rezervasyon gerektirir; bu, "yalnız başarılı gönderimden sonra yaz" kuralıyla çelişir. KARAR: kabul edilmiş risk. Kaynak: `backend/auth.py` (`_mail_kotasi_var`, `_postalari_gonder`).

### Ajan kopyası ayrışması
- **Kategori:** teknik borç
- **Neden:** `agent/agent.py` (kaynak) ile `frontend/static/agent/agent.py` (indirilen kopya) ayrışmış; kopya daha yeni (`--key-file`, `NEXMEET_AGENT_KEY`, anahtar maskeleme).
- **Notlar:** kaynak indirilen kopyaya eşitlenmeli; ardından iki dosyanın eşitliği kontrol edilmeli. Bkz. `task.md`.

### Eski TURN alan adı geçmişte
- **Kategori:** teknik borç (güvenlik hijyeni)
- **Neden:** eski commit'lerde `TURN_URLS` satırındaki TURN alan adı duruyor. Parola ve IP'ler temizlendi; alan adı temizlenmedi.
- **Notlar:** KARAR BEKLİYOR: geçmiş yeniden yazılıp zorla yüklensin mi?

### Kökteki start.bat (kapandı)
- **Kategori:** teknik borç
- **Neden:** kişisel bir Windows yolu içeriyordu; `scripts/start.bat` ile ayrışmıştı.
- **Notlar:** Kullanıcı onayıyla silindi (`chore/kaldir-kok-start-bat`). Tek kopya `scripts/start.bat`.

## Ekleme Şablonu

```markdown
### Başlık
- **Kategori:** yeni özellik / iyileştirme / teknik borç / araştırma
- **Neden:** kısa gerekçe
- **Notlar:** büyüklük, bağımlılıklar, riskler
```
