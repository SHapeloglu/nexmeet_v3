# CLAUDE.md

Bu dosya, bu proje üzerinde çalışırken Claude'un (Claude Code dahil) izlemesi gereken bağlamı ve kuralları içerir.

## Proje

**🎥 NexMeet — Gerçek Zamanlı Video Konferans** — WebRTC tabanlı, **ses klonlamalı anlık çeviri**, **uzak masaüstü kontrolü** ve **dosya paylaşımı** özelliklerine sahip modern video konferans platformu. 🌐 **Canlı Demo:** [nexmeet.powerbi.com.tr](https://nexmeet.powerbi.com.tr)

- GitHub: https://github.com/SHapeloglu/nexmeet_v3
- Sunucu (Contabo): canlı dizin /root/nexmeet (backend systemd servisi)

## Teknoloji Yığını

- FastAPI
- Uvicorn
- Docker / docker compose
- Bash betikleri

## Önemli Dosyalar

- `agent/requirements.txt`
- `backend/main.py`
- `backend/requirements.txt`
- `docker/Dockerfile`
- `docker/backend/main.py`
- `docker/backend/requirements.txt`
- `docker/docker-compose.yml`
- `frontend/index.html`

Mimari ayrıntılar için bkz. `architect.md`.

## Sık Kullanılan Komutlar

```bash
docker compose up -d --build
docker compose logs -f
```

## Kurallar

- Yapılandırmayı ortam değişkenlerinden oku; endpoint şemalarını Pydantic modelleriyle tanımla.
- Bloklayan I/O işlemlerini async endpoint içinde doğrudan çağırma.
- `.env`, parola, token ve API anahtarlarını asla commit etme.
- Her çalışma oturumunun sonunda `session.md`ye kısa kayıt düş; görev durumunu `task.md`de güncelle.
- Önceliklendirilmemiş fikirleri `backlog.md`ye yaz; somutlaşınca `task.md`ye taşı.

## Çalışma Dosyaları

| Dosya | Amaç |
|---|---|
| `architect.md` | Mimari ve dizin yapısı referansı |
| `task.md` | Aktif / devam eden / tamamlanan görevler |
| `backlog.md` | Önceliklendirilmemiş fikir ve teknik borç havuzu |
| `session.md` | Oturum günlüğü — her oturum sonunda güncellenir |
