# CLAUDE.md — NexMeet (v3, canlı)

WebRTC tabanlı video konferans: oda + katılımcı başına 1 saatlik join token, WebSocket sinyalizasyon (offer/answer/ICE), sohbet (son 50 mesaj), dosya paylaşımı (100 MB, MIME doğrulama, 1 saat sonra otomatik silme), tarayıcıda kayıt (WebM), ekran paylaşımı, **uzak masaüstü kontrolü** (indirilebilir Python ajan) ve **anlık konuşma çevirisi** (TR → EN, ayrı TTS servisi üzerinden).

- GitHub: https://github.com/SHapeloglu/nexmeet_v3 — **PUBLIC repo**
- **Canlı:** Docker Compose, sunucuda `/opt/nexmeet` (repo dışı). Konteynerler: `nexmeet` (uvicorn, `127.0.0.1:8009`, ortam `nexmeet.env`, yüklemeler `./uploads` volume) ve `nexmeet-tts` (ortam `tts.env`). İkisi de `restart unless-stopped`; ağlar: `nexmeet` ve dış `ortak-db`. Public adres nginx arkasında: `nexmeet.powerbiegitimi.com`. Sunucuda otomatik uyku (AutoSleep) mekanizması var.
- TTS servisi: `nexmeet-tts` konteyneri (Kokoro ONNX, CPU). Backend `TTS_SERVICE_URL` / `TTS_API_KEY` ile çağırır. Kaynağı bu repoda değil, yalnızca sunucuda.
- Eski systemd birimleri (`nexmeet.service`, `nexmeet-tts.service`) kaldırıldı.
- Önceki sürümler: `nexmeet_v1` (05-14), `nexmeet_v2` (06-25) ve `nexmeet_v2-kokoro-tts-service` (GPU'lu EC2 tasarımı).
- Mimari: `architect.md` · Görevler: `task.md` · Fikirler: `backlog.md` · Günlük: `session.md`

## Komutlar

```bash
# Canlı (sunucuda)
docker ps --filter name=nexmeet          # konteyner durumu
docker logs -f nexmeet                   # canlı log
docker restart nexmeet                   # yeniden başlat (kod değişikliği imajın yeniden derlenmesini gerektirir; compose dosyası /opt/nexmeet'te)

# Yerel geliştirme
python3 -m venv venv && . venv/bin/activate
pip install -r backend/requirements.txt
cd backend && uvicorn main:app --reload --port 8000     # main.py __main__ da bunu yapar
```

Ortam değişkenleri: `SECRET_KEY, ALLOWED_ORIGINS, MAX_FILE_SIZE_MB, UPLOADS_DIR, HOST, PORT, TTS_SERVICE_URL, TTS_API_KEY` ve üyelik/posta ayarları (bkz. `.env.example`). Canlıda değerler `/opt/nexmeet` altındaki `nexmeet.env` ve `tts.env` dosyalarından gelir; bu dosyaların içeriği repoya ve belgelere yazılmaz.

## Kurallar ve Tuzaklar

- **Dağıtım:** Canlı yol Docker'dır. `README.md` ve `architect.md` bunu anlatır; repodaki `docker/` klasörü canlı kurulumun yerel karşılığıdır (TTS hariç).
- Ses klonlama yok: TTS CPU'da Kokoro ONNX ile sabit `af_heart` sesiyle çalışır.
- `backend/tts/` (torch + whisper, `/home/ubuntu/...` yolları) **kullanılmıyor** — `main.py` import etmiyor; EC2 tasarımından kalıntı. `backend/app.js` frontend `app.js`'in eski kopyası, - Ajan iki yerde: `agent/` (kaynak) ve `frontend/static/agent/` (kullanıcıya indirilen kopya) — ikisi farklı; ajan değişince indirilen kopyayı güncelle.
- `SECRET_KEY` ortamda yoksa her başlatmada rastgele üretilir → tüm join token'lar geçersiz olur.
- **Public repo:** `uploads/` `.gitignore`'da ama içindeki 2 kullanıcı dosyası (PDF, JPG) izleniyor; `.env` asla commit edilmez, IP/anahtar yazma.
- Frontend tek dosya (`frontend/static/js/app.js`, ~1.650 satır); state nesnesi en üstte.
- Oturum sonunda `session.md`'ye kayıt düş, `task.md`'yi güncelle.
