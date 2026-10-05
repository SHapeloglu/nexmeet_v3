# architect.md — 🎥 NexMeet — Gerçek Zamanlı Video Konferans Mimari Referansı

Bu dosya projenin yapısının hızlı-referans özetidir. Kod değiştikçe güncel tutun.

## Genel Bakış

WebRTC tabanlı, **ses klonlamalı anlık çeviri**, **uzak masaüstü kontrolü** ve **dosya paylaşımı** özelliklerine sahip modern video konferans platformu. 🌐 **Canlı Demo:** [nexmeet.powerbi.com.tr](https://nexmeet.powerbi.com.tr)

## Teknoloji Yığını

- FastAPI
- Uvicorn
- Docker / docker compose
- Bash betikleri

## Dizin Yapısı

```
.env.example
.gitignore
README.md
agent/
  agent.py
  linux_agent.sh
  requirements.txt
  run_agent.bat
  run_agent.sh
  windows_agent.bat
backend/
  __init__.py
  app.js
  main.py
  requirements.txt
  tts/
docker/
  Dockerfile
  backend/
  docker-compose.yml
frontend/
  index.html
scripts/
  start.bat
  start.sh
start.bat
uploads/
  2451bf69-0332-41c3-839d-3f2e3cffe9a7_12_03_2026_en.pdf
  6ba37304-ffec-423f-a724-1e85c99dfe54_image.jpg
```

## Modüller / Kaynak Dosyalar

- `agent/agent.py` — NexMeet Uzak Kontrol Ajanı
- `agent/linux_agent.sh`
- `agent/run_agent.sh`
- `backend/app.js`
- `backend/main.py`
- `scripts/start.sh` — NexMeet Başlatma Scripti (Linux/macOS)
- `backend/tts/chunker.py`
- `backend/tts/engine.py`
- `backend/tts/queue.py`
- `docker/backend/main.py`

## Giriş Noktaları ve Yapılandırma

- `agent/requirements.txt`
- `backend/main.py`
- `backend/requirements.txt`
- `docker/Dockerfile`
- `docker/backend/main.py`
- `docker/backend/requirements.txt`
- `docker/docker-compose.yml`
- `frontend/index.html`

## Dağıtım / Çalışma Ortamı

- GitHub: https://github.com/SHapeloglu/nexmeet_v3
- Sunucu (Contabo): canlı dizin /root/nexmeet (backend systemd servisi)

## Diğer Dokümanlar

- `README.md`

## Mimari Kararlar

_Önemli tasarım kararlarını ve gerekçelerini buraya ekleyin (ör. "X yerine Y seçildi çünkü ...")._
