# architect.md — NexMeet (v3) Mimarisi

```
Tarayıcı (frontend/index.html + static/js/app.js)
  │ 1) POST /api/join-token → 1 saatlik token
  │ 2) WS /ws/{room}/{peer}  (sinyalizasyon, chat, durum)
  │ 3) WebRTC P2P (medya; STUN/TURN)
  ▼
nginx (nexmeet.powerbiegitimi.com) → FastAPI backend/main.py (127.0.0.1:8009, systemd nexmeet)
  ├─ /api/upload/{room}, /api/download/{file_id}?token, /api/room/{room}/files  → uploads/ (TTL 1 saat)
  ├─ WS /ws/agent/{agent_id}                      ← uzak kontrol ajanı (agent.py, kontrol edilen PC)
  ├─ WS /ws/control/{session}/{controller_peer}   ← kontrol eden tarayıcı
  ├─ /api/control/request|respond|stop            ← izin akışı
  └─ /api/tts/synthesize, /api/tts/voice-profile[/status] ──HTTP X-API-Key──► nexmeet-tts (127.0.0.1:5000)
                                                                               faster-whisper tiny (STT, CPU)
                                                                               → GoogleTranslator (TR→EN)
                                                                               → Kokoro ONNX (TTS, af_heart)
```

## Backend (`backend/main.py`)

- Durum bellekte (odalar, peer'lar, paylaşılan dosyalar, kontrol oturumları) — tek süreç; yeniden başlatmada sıfırlanır.
- Token: `generate_join_token` / `validate_join_token` (`SECRET_KEY` ile imzalı, 1 saat), `cleanup_expired_tokens`.
- Dosya: `validate_file` (uzantı + MIME + boyut), `auto_delete_file` (`FILE_TTL_SECONDS = 3600`).
- CORS: `ALLOWED_ORIGINS`.

## Uzak Kontrol

Kontrol edilecek bilgisayarda `agent.py` (Windows `.bat` / Linux `.sh` başlatıcılarıyla) çalışır, backend'e WS ile bağlanır (2026-07-20'de ajan token doğrulaması eklendi); kontrol eden katılımcı istek gönderir, karşı taraf onaylar, fare/klavye olayları backend üzerinden ajana iletilir.

## Dağıtım

- systemd `nexmeet.service`: `/root/nexmeet/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8009`.
- systemd `nexmeet-tts.service`: aynı venv, `/root/nexmeet-tts`, port 5000, `API_KEY` unit dosyasında.
- `docker/` klasörü eski; canlıda kullanılmıyor.

## Mimari Kararlar

- **P2P medya, sunucu sadece sinyalizasyon** — sunucu maliyeti düşük; çok katılımcıda tarayıcı yükü artar (SFU yok).
- **Çeviri ayrı servis** — ağır modeller backend'i bloklamasın; v2'de GPU EC2 + ses klonlama planlandı, v3'te maliyet için CPU Kokoro'ya inildi.
- **Bellekte durum** — basitlik; yatay ölçekleme yok.
