# NexMeet backend + arayüz imajı (canlı sunucudaki Dockerfile.nexmeet ile aynı mantık).
# Build bağlamı repo kökü olmalı: docker-compose.yml içinde context: .. olarak ayarlı.
FROM python:3.12-slim

WORKDIR /app

# Bağımlılıkları önce kopyala (cache için)
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodunu kopyala
COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend

EXPOSE 8009

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009"]
