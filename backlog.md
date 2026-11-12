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

## Ekleme Şablonu

```markdown
### Başlık
- **Kategori:** yeni özellik / iyileştirme / teknik borç / araştırma
- **Neden:** kısa gerekçe
- **Notlar:** büyüklük, bağımlılıklar, riskler
```
