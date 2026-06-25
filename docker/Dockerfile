FROM python:3.11-slim

WORKDIR /app

# Bağımlılıkları önce kopyala (cache için)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodunu kopyala
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# uploads klasörü kalıcı olsun (volume mount noktası)
RUN mkdir -p /app/uploads

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
