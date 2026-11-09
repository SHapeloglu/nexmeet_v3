# NexMeet TTS servisi (kaynak)

Konuşma çevirisi hattı: ses → faster-whisper (STT) → Argos ile TR→EN çeviri → Kokoro ONNX (TTS, CPU, sabit ses).
Canlıda `nexmeet-tts` konteyneri olarak çalışır; backend (`backend/main.py`) `/api/tts/*` uçlarından çağırır.

Bu klasör yalnızca kaynak kodu içerir. Büyük model dosyaları repoda **yoktur**; konteynere bağlanır:

- `kokoro-v1.0.onnx`, `voices-v1.0.bin`: Kokoro ONNX model ve ses dosyaları
- `models/translate-tr_en-1_5/`: Argos TR→EN çeviri modeli
- `voice_profiles/`, `hf/`: çalışma zamanı verileri (Whisper önbelleği, vb.)

Ortam değişkeni: `API_KEY` (zorunlu; yoksa servis başlamaz). Değer repoya yazılmaz; konteynerde `tts.env` ile verilir.

Yerelde çalıştırma (model dosyalarıyla birlikte):

```bash
docker build -f tts-service/Dockerfile.tts -t nexmeet-tts tts-service
```

Build bağlamı `tts-service/` olmalı (`COPY requirements.txt`, `COPY main.py`).
