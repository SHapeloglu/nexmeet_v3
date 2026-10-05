# CLAUDE.md — NexMeet (v3, canlı)

WebRTC tabanlı video konferans: oda + katılımcı başına 1 saatlik join token, WebSocket sinyalizasyon (offer/answer/ICE), sohbet (son 50 mesaj), dosya paylaşımı (100 MB, MIME doğrulama, 1 saat sonra otomatik silme), tarayıcıda kayıt (WebM), ekran paylaşımı, **uzak masaüstü kontrolü** (indirilebilir Python ajan) ve **anlık konuşma çevirisi** (TR → EN, ayrı TTS servisi üzerinden).

- GitHub: https://github.com/SHapeloglu/nexmeet_v3 — **PUBLIC repo**
- **Canlı:** bu klasör. `nexmeet.service` → `uvicorn main:app` `127.0.0.1:8009` (WorkingDirectory `backend/`, `EnvironmentFile=/root/nexmeet/.env`), nginx `nexmeet.powerbiegitimi.com`.
- TTS servisi: `/root/nexmeet-tts` (`nexmeet-tts.service`, `127.0.0.1:5000`) — backend `TTS_SERVICE_URL` / `TTS_API_KEY` ile çağırır.
- Önceki sürümler: `nexmeet_v1` (05-14), `nexmeet_v2` (06-25) ve `nexmeet_v2-kokoro-tts-service` (GPU'lu EC2 tasarımı).
- Mimari: `architect.md` · Görevler: `task.md` · Fikirler: `backlog.md` · Günlük: `session.md`

## Komutlar

```bash
cd /root/nexmeet && . venv/bin/activate
pip install -r backend/requirements.txt
sudo systemctl restart nexmeet && journalctl -u nexmeet -f
cd backend && uvicorn main:app --reload --port 8000     # yerel geliştirme (main.py __main__ da bunu yapar)
```

`.env` anahtarları: `SECRET_KEY, ALLOWED_ORIGINS, MAX_FILE_SIZE_MB, UPLOADS_DIR, HOST, PORT, TTS_SERVICE_URL, TTS_API_KEY` (bkz. `.env.example`).

## Kurallar ve Tuzaklar

- **README mimarisi güncel değil:** AWS EC2 (c7i-flex + g4dn GPU, ChatterboxTTS ses klonlama) anlatıyor ve IP adresleri içeriyor; canlıda her şey bu Contabo sunucusunda, TTS CPU'da Kokoro ONNX ile **ses klonlamadan** (sabit `af_heart` sesi) çalışıyor.
- `backend/tts/` (torch + whisper, `/home/ubuntu/...` yolları) **kullanılmıyor** — `main.py` import etmiyor; EC2 tasarımından kalıntı. `backend/app.js` frontend `app.js`'in eski kopyası, `docker/backend/main.py` eski sürüm.
- Ajan iki yerde: `agent/` (kaynak) ve `frontend/static/agent/` (kullanıcıya indirilen kopya) — ikisi farklı; ajan değişince indirilen kopyayı güncelle.
- `SECRET_KEY` ortamda yoksa her başlatmada rastgele üretilir → tüm join token'lar geçersiz olur.
- **Public repo:** `uploads/` `.gitignore`'da ama içindeki 2 kullanıcı dosyası (PDF, JPG) izleniyor; `.env` asla commit edilmez, IP/anahtar yazma.
- Frontend tek dosya (`frontend/static/js/app.js`, ~1.650 satır); state nesnesi en üstte.
- Oturum sonunda `session.md`'ye kayıt düş, `task.md`'yi güncelle.
