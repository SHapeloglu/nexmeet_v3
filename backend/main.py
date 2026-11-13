"""NexMeet ana sunucusu (FastAPI). Uygulamanın giriş noktasıdır: sayfa yönlendirmeleri, join token üretimi, dosya yükleme ve indirme, WebSocket sinyalizasyonu (WebRTC offer, answer, ICE), uzak masaüstü kontrol oturumları ve TTS proxy uçları burada tanımlıdır.
Üyelik uçları auth.py, veritabanı işleri db.py, e-posta gönderimi mailer.py dosyasındadır.
Join token, dosya kayıtları ve oda durumu bellekte tutulur. Sunucu yeniden başlarsa silinir; bu yüzden tek süreçle (tek uvicorn worker) çalıştırılmalıdır.
Çalıştırma: systemd servisi "uvicorn main:app" komutunu backend/ dizininden başlatır."""
import json
import uuid
import logging
import os
import time
import secrets
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlencode
from dotenv import load_dotenv

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect,
    UploadFile, File, Form, HTTPException,
    Depends, Header, Request
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import asyncio
import aiofiles
import pymysql

import auth
import db

# ─── Config ──────────────────────────────────────────────────────────────────
load_dotenv()

# DİKKAT: Bu değişken kodda başka yerde kullanılmıyor. Join token'lar SECRET_KEY'den türetilmez; rastgele üretilip bellekte tutulur.
# Sunucu yeniden başlarsa tüm token'lar ve kontrol oturumları silinir.
SECRET_KEY    = os.getenv("SECRET_KEY", secrets.token_hex(32))
RAW_ORIGINS   = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000")
ALLOWED_ORIGINS = [o.strip() for o in RAW_ORIGINS.split(",") if o.strip()]
# Dosya boyut sınırı (bayt). MB cinsinden MAX_FILE_SIZE_MB ortam değişkeninden okunur; ayar yoksa 50 MB kullanılır.
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "50")) * 1024 * 1024

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".msi",
    ".dll", ".so", ".dylib", ".bin", ".com", ".scr",
    ".vbs", ".js", ".jar", ".py", ".php", ".rb",
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Üyelik tabloları. Başarısızsa uygulama yine açılır; üyelik uçları 503 döner.
    """Uygulama açılırken ve kapanırken çalışan yaşam döngüsü. Açılışta üyelik tablolarını oluşturur. Veritabanı yoksa uygulama yine açılır; yalnız üyelik uçları 503 döner."""
    try:
        await asyncio.to_thread(db.sema_olustur)
        logger.info("Üyelik veritabanı hazır (%s:%s/%s).",
                    os.getenv("DB_HOST", "127.0.0.1"), os.getenv("DB_PORT", "3306"),
                    os.getenv("DB_NAME", "nexmeet"))
    except Exception as e:  # noqa: BLE001
        logger.error(
            "Üyelik veritabanı hazır değil (%s: %s). Giriş/kayıt uçları 503 dönecek; "
            "toplantı özellikleri etkilenmez. DB_HOST/DB_PORT/DB_USER/DB_NAME ayarlarını kontrol edin.",
            type(e).__name__, e,
        )
    yield

FILE_TTL_SECONDS = 3600  # Dosyalar 1 saat sonra silinir (değiştirilebilir)

async def auto_delete_file(file_id: str, path: str, delay: int):
    """Belirtilen süre sonra dosyayı sil."""
    await asyncio.sleep(delay)
    shared_files.pop(file_id, None)
    try:
        if os.path.exists(path):
            os.unlink(path)
            logger.info(f"Otomatik silindi: {path}")
    except Exception as e:
        logger.error(f"Silme hatası: {e}")

# ─── Rate Limiter (üyelik uçlarıyla aynı örnek) ───────────────────────────────
limiter = auth.limiter
app = FastAPI(title="NexMeet", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(pymysql.MySQLError)
async def veritabani_hatasi(_request: Request, exc: pymysql.MySQLError):
    """Üyelik tarafındaki veritabanı hatalarını yakalar ve kullanıcıya 503 yanıtı döner. Ham hata metni istemciye gönderilmez, yalnız loglanır."""
    logger.error("Veritabanı hatası: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Üyelik servisi şu an kullanılamıyor. Lütfen daha sonra tekrar deneyin."},
    )


app.include_router(auth.router)

# ─── CORS (production'da * yasak) ────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR  = BASE_DIR / os.getenv("UPLOADS_DIR", "uploads")
UPLOADS_DIR.mkdir(exist_ok=True)


def temizle_eski_yuklemeler():
    """Başlangıçta FILE_TTL_SECONDS'tan eski dosyaları sil (yeniden başlatmada yetim kalanlar)."""
    sinir = time.time() - FILE_TTL_SECONDS
    for f in UPLOADS_DIR.iterdir():
        try:
            if f.is_file() and f.name != ".gitkeep" and f.stat().st_mtime < sinir:
                f.unlink()
                logger.info(f"Yetim dosya silindi: {f.name}")
        except Exception as e:
            logger.error(f"Yetim dosya silinemedi ({f.name}): {e}")


temizle_eski_yuklemeler()

# ─── In-memory state ─────────────────────────────────────────────────────────
shared_files:    Dict[str, dict] = {}
control_sessions: Dict[str, dict] = {}
agent_connections: Dict[str, WebSocket] = {}

# ─── Join token'ları (oda başına basit token) ─────────────────────────────────
# token -> {room_id, peer_id, name, user_id, expires_at}
join_tokens: Dict[str, dict] = {}


def generate_join_token(room_id: str, peer_id: str, name: str, user_id: Optional[int] = None) -> str:
    """Oda bağlantısı için kısa süreli token oluştur."""
    token = secrets.token_urlsafe(32)
    join_tokens[token] = {
        "room_id": room_id,
        "peer_id": peer_id,
        "name": name,
        "user_id": user_id,
        "expires_at": time.time() + 3600,  # 1 saat geçerli
    }
    return token


def _hesap_silinince_tokenlari_sil(user_id: int) -> None:
    """Hesap silindiğinde o kullanıcıya ait join token'larını geçersiz kıl."""
    silinecek = [t for t, v in list(join_tokens.items()) if v.get("user_id") == user_id]
    for t in silinecek:
        join_tokens.pop(t, None)


auth._hesap_silindi_kancalari.append(_hesap_silinince_tokenlari_sil)


def validate_join_token(token: str) -> Optional[dict]:
    """Token'ı doğrula, süresi dolmuşsa sil."""
    entry = join_tokens.get(token)
    if not entry:
        return None
    if time.time() > entry["expires_at"]:
        del join_tokens[token]
        return None
    return entry


def cleanup_expired_tokens():
    """Süresi dolmuş token'ları temizle."""
    now = time.time()
    expired = [t for t, v in list(join_tokens.items()) if now > v["expires_at"]]
    for t in expired:
        del join_tokens[t]
    # Token ömrünü (1 saat) aşan kontrol oturumları da düşer
    eski = [sid for sid, v in control_sessions.items() if now - v.get("created_at", now) > 3600]
    for sid in eski:
        del control_sessions[sid]


def validate_file(filename: str, content_type: str, content: bytes) -> str:
    """
    Dosya adının uzantısını doğrular; yalnız BLOCKED_EXTENSIONS içindeki uzantılar reddedilir.
    MIME tipi (content_type) ve içerik (content) DENETLENMEZ: bu parametreler imza uyumluluğu için duruyor ama kullanılmıyor.
    Sorun varsa HTTPException fırlatır.
    Temizlenmiş dosya adını döndürür.
    """
    safe_name = os.path.basename(filename or "file")
    ext = Path(safe_name).suffix.lower()

    if ext in BLOCKED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"'{ext}' uzantılı dosyalar güvenlik nedeniyle yüklenemez."
        )

    # Yalnız uzantı denetlenir; MIME tipi bilinçli olarak kontrol edilmez.

    return safe_name


# ─── Connection Manager ───────────────────────────────────────────────────────
class ConnectionManager:
    """Odalardaki WebSocket bağlantılarını, peer adlarını ve oda sohbet geçmişini bellekte tutan yardımcı sınıf. Bu sınıf tek bir sunucu süreci içinde çalışır."""
    def __init__(self):
        """Boş oda sözlüklerini oluşturur. rooms: oda -> {peer_id: WebSocket}, peer_names: peer_id -> ad, chat_history: oda -> son 50 mesaj."""
        self.rooms: Dict[str, Dict[str, WebSocket]] = {}
        self.peer_names: Dict[str, str] = {}
        # Son 50 sohbet mesajını oda bazında sakla
        self.chat_history: Dict[str, list] = {}

    async def connect(self, websocket: WebSocket, room_id: str, peer_id: str, name: str):
        """Peer'in WebSocket bağlantısını kabul eder ve odaya ekler. Oda yoksa önce oluşturulur, yani ilk katılan kişi odayı açar."""
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
            self.chat_history[room_id] = []
        self.rooms[room_id][peer_id] = websocket
        self.peer_names[peer_id] = name
        logger.info(f"Peer {peer_id} ({name}) joined room {room_id}")

    def disconnect(self, room_id: str, peer_id: str):
        """Peer'i odadan çıkarır. Oda boşalırsa odayı ve sohbet geçmişini de siler. Peer zaten yoksa hata vermez."""
        if room_id in self.rooms:
            self.rooms[room_id].pop(peer_id, None)
            if not self.rooms[room_id]:
                del self.rooms[room_id]
                self.chat_history.pop(room_id, None)  # Oda boşaldı, geçmişi temizle
        self.peer_names.pop(peer_id, None)
        logger.info(f"Peer {peer_id} left room {room_id}")

    async def send_to_peer(self, room_id: str, peer_id: str, message: dict):
        """Tek bir peer'a JSON mesajı gönderir. Peer yoksa ya da gönderim hata verirse sessizce geçer; hata yalnız loglanır."""
        if room_id in self.rooms and peer_id in self.rooms[room_id]:
            try:
                await self.rooms[room_id][peer_id].send_json(message)
            except Exception as e:
                logger.error(f"Error sending to peer {peer_id}: {e}")

    async def broadcast_to_room(self, room_id: str, message: dict, exclude_peer: str = None):
        """Odadaki herkese mesaj gönderir. exclude_peer verilirse o peer atlanır. Bir peer'e gönderim hata verirse diğerleri etkilenmez."""
        if room_id not in self.rooms:
            return
        for peer_id, ws in list(self.rooms[room_id].items()):
            if peer_id != exclude_peer:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to peer {peer_id}: {e}")

    def get_room_peers(self, room_id: str) -> list:
        """Odadaki peer'lerin {id, name} listesini döner. Oda yoksa boş liste döner."""
        if room_id not in self.rooms:
            return []
        return [
            {"id": pid, "name": self.peer_names.get(pid, "Unknown")}
            for pid in self.rooms[room_id].keys()
        ]


manager = ConnectionManager()


# ─── HTTP Endpoints ───────────────────────────────────────────────────────────

def _girise_yonlendir(yol: str) -> RedirectResponse:
    """Oturumu olmayan kullanıcıyı /giris sayfasına 302 ile yönlendirir. Dönüş adresi next parametresinde taşınır, böylece girişten sonra aynı sayfaya dönülür."""
    return RedirectResponse(url="/giris?" + urlencode({"next": yol}), status_code=302)


@app.get("/")
async def root(request: Request):
    """Ana sayfa. Oturum varsa uygulama arayüzünü (index.html) verir, yoksa giriş sayfasına yönlendirir."""
    if not await auth.oturum_var_mi(request):
        return _girise_yonlendir("/")
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/room/{room_id}")
async def get_room(request: Request, room_id: str):
    """Oda sayfası. Oturum yoksa giriş sayfasına yönlendirir ve dönüş adresi olarak bu odayı verir."""
    if not await auth.oturum_var_mi(request):
        return _girise_yonlendir(f"/room/{room_id}")
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/saglik")
async def saglik():
    # Veritabanı durumunu canlı kontrol eder; toplantı servisi DB'den bağımsız çalışır.
    """Sağlık kontrolü ucu. Servis çalışıyorsa her zaman 'tamam' döner. Veritabanı durumu ayrı bir alanda (db) bildirilir; izleme araçları için kullanılır."""
    try:
        await asyncio.to_thread(db.kontrol)
        db_durum = "tamam"
    except Exception as e:  # noqa: BLE001
        logger.error("Sağlık kontrolü: veritabanı hatası (%s: %s)", type(e).__name__, e)
        db_durum = "hata"
    return {"durum": "tamam", "db": db_durum}


@app.get("/api/room/{room_id}/info")
async def room_info(room_id: str):
    # Katılımcı adları/kimlikleri tokensiz verilmez; yalnız sayı döner.
    """Odanın yalnız katılımcı sayısını döner. Katılımcı adları ve kimlikleri token olmadan verilmez."""
    return {"room_id": room_id, "peer_count": len(manager.get_room_peers(room_id))}


@app.post("/api/join-token")
@limiter.limit("20/minute")
async def create_join_token(request: Request, data: dict):
    """
    Oda katılım token'ı oluştur. Yalnız giriş yapmış ve doğrulanmış kullanıcıya verilir.
    Görünen ad hesaptan gelir; istemciden alınan ad yok sayılır.
    """
    auth.origin_kontrol(request)
    kullanici = await auth.oturumlu_kullanici(request)
    name    = str(kullanici["display_name"]).strip()[:50]
    room_id = str(data.get("room_id", "")).strip()[:20]

    if not room_id:
        raise HTTPException(status_code=400, detail="room_id zorunlu.")

    # peer_id istemciden alınmaz: sunucu üretir, başkası aynı kimliği isteyemez.
    peer_id = secrets.token_urlsafe(9)

    cleanup_expired_tokens()
    token = generate_join_token(room_id, peer_id, name, kullanici["id"])
    return {"token": token, "peer_id": peer_id}


@app.post("/api/upload/{room_id}")
@limiter.limit("10/minute")
async def upload_file(
    request: Request,
    room_id: str,
    file: UploadFile = File(...),
    peer_id: str = Form(...),
    token: str = Form(...),
):
    """Dosya yükle — token doğrulaması zorunlu. Yükleyenin adı doğrulanmış join token'dan (entry["name"]) alınır; istemciden gelen ad yok sayılır."""
    # Token doğrula
    entry = validate_join_token(token)
    if not entry or entry["room_id"] != room_id or entry["peer_id"] != peer_id:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş token.")
    uploader_name = entry["name"]

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"Dosya çok büyük (max {MAX_FILE_SIZE // 1024 // 1024} MB)")

    safe_name = validate_file(file.filename or "file", file.content_type or "", content)

    file_id   = str(uuid.uuid4())
    save_path = str(UPLOADS_DIR / f"{file_id}_{safe_name}")

    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    meta = {
        "file_id":   file_id,
        "name":      safe_name,
        "size":      len(content),
        "type":      file.content_type or "application/octet-stream",
        "uploader":  uploader_name,
        "peer_id":   peer_id,
        "room_id":   room_id,
        "path":      save_path,
        "timestamp": time.strftime("%H:%M"),
    }
    shared_files[file_id] = meta

    await manager.broadcast_to_room(room_id, {
        "type":      "file-shared",
        "file_id":   file_id,
        "name":      safe_name,
        "size":      len(content),
        "mime_type": meta["type"],
        "uploader":  uploader_name,
        "timestamp": meta["timestamp"],
    })

    logger.info(f"File uploaded: {safe_name} ({len(content)} bytes) by {uploader_name} in {room_id}")
    # Otomatik silme zamanlayıcısı
    asyncio.create_task(auto_delete_file(file_id, save_path, FILE_TTL_SECONDS))
    return {"file_id": file_id, "name": safe_name, "ttl": FILE_TTL_SECONDS}


@app.get("/api/download/{file_id}")
@limiter.limit("30/minute")
async def download_file(request: Request, file_id: str, token: str):
    """Dosya indir — token zorunlu."""
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş token.")

    meta = shared_files.get(file_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")

    # Token sahibi bu odada mı?
    if entry["room_id"] != meta["room_id"]:
        raise HTTPException(status_code=403, detail="Bu dosyaya erişim yetkiniz yok.")

    if not os.path.exists(meta["path"]):
        raise HTTPException(status_code=404, detail="Dosya sunucudan silinmiş")

    # media_type yükleyenin gönderdiği değerdir. Tarayıcıda çalışabilen türler (HTML, SVG, XML, JS) her zaman düz ikili veri olarak sunulur;
    # ayrıca nosniff (tür tahmini yapma), indirme olarak sun (attachment) ve sandbox CSP başlıkları eklenir.
    tur = (meta["type"] or "application/octet-stream").lower()
    if any(t in tur for t in ("html", "svg", "xml", "javascript", "ecmascript")):
        tur = "application/octet-stream"
    return FileResponse(
        meta["path"], filename=meta["name"], media_type=tur, content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )


@app.get("/api/room/{room_id}/files")
async def room_files(room_id: str, token: str):
    """Odada paylaşılan dosyaları listele — token zorunlu."""
    entry = validate_join_token(token)
    if not entry or entry["room_id"] != room_id:
        raise HTTPException(status_code=401, detail="Geçersiz token.")

    files = [
        {k: v for k, v in m.items() if k != "path"}
        for m in shared_files.values()
        if m["room_id"] == room_id
    ]
    return {"files": files}


# ─── WebSocket: Oda sinyalizasyonu ───────────────────────────────────────────

# ─── WebSocket: Agent ─────────────────────────────────────────────────────────

@app.websocket("/ws/agent/{agent_id}")
async def agent_endpoint(websocket: WebSocket, agent_id: str):
    """Uzak masaüstü ajanının WebSocket bağlantısı (/ws/agent/{agent_id}). Ajan yalnız onaylanmış bir kontrol oturumu ve o oturuma özel tek kullanımlık ajan anahtarıyla bağlanabilir. Ajanın gönderdiği ekran kareleri (frame) kontrolcüye iletilir."""
    # DİKKAT: Ajan anahtarı bağlantı adresinde (query) taşınır. Sunucu veya proxy erişim logu adresi yazarsa anahtar loglara düşebilir.
    # Tek kullanımlık olması ve kısa ömürlü oturum bu riski sınırlar.
    key        = websocket.query_params.get("key", "")
    session_id = websocket.query_params.get("session_id", "")
    session    = control_sessions.get(session_id)

    # Agent doğrulama: oturum gerçek, hedef onaylamış ve tek kullanımlık ajan anahtarı doğru mu?
    if not session or not session.get("approved"):
        await websocket.close(code=4001, reason="Geçersiz veya onaylanmamış oturum")
        return

    expected = session.get("agent_key")
    if not expected or not key or not secrets.compare_digest(key, expected):
        await websocket.close(code=4001, reason="Geçersiz ajan anahtarı")
        return
    session["agent_key"] = None  # tek kullanımlık

    await websocket.accept()
    agent_connections[agent_id] = websocket
    logger.info(f"Agent connected: {agent_id}")

    try:
        while True:
            data     = await websocket.receive_json()
            msg_type = data.get("type")
            sess_id  = data.get("session_id")

            if msg_type == "frame":
                sess = control_sessions.get(sess_id)
                if sess and sess.get("approved") and sess.get("controller_ws"):
                    try:
                        await sess["controller_ws"].send_json({
                            "type":       "remote-frame",
                            "session_id": sess_id,
                            "frame":      data.get("frame"),
                            "width":      data.get("width"),
                            "height":     data.get("height"),
                        })
                    except Exception:
                        pass

            elif msg_type == "agent-ready":
                sess = control_sessions.get(sess_id)
                if sess:
                    sess["agent_ws"] = websocket
                    sess["agent_id"] = agent_id

    except WebSocketDisconnect:
        agent_connections.pop(agent_id, None)
        for sid, sess in list(control_sessions.items()):
            if sess.get("agent_id") == agent_id:
                ctrl_ws = sess.get("controller_ws")
                if ctrl_ws:
                    try:
                        await ctrl_ws.send_json({"type": "remote-disconnected", "session_id": sid})
                    except Exception:
                        pass
                del control_sessions[sid]
        logger.info(f"Agent disconnected: {agent_id}")
    except Exception as e:
        logger.error(f"Agent error {agent_id}: {e}")
        agent_connections.pop(agent_id, None)


async def _peer_kontrol_oturumlarini_iptal_et(peer_id: str) -> None:
    """Peer ayrıldığında, o peer'ın kontrolcü ya da hedef olduğu tüm kontrol oturumlarını iptal eder: onayı kaldırır, ajana stop-control gönderir (hata yutulur) ve oturumu siler."""
    for sid, sess in list(control_sessions.items()):
        if peer_id not in (sess.get("controller_peer_id"), sess.get("target_peer_id")):
            continue
        sess["approved"] = False
        agent_ws = sess.get("agent_ws")
        if agent_ws:
            try:
                await agent_ws.send_json({"type": "stop-control", "session_id": sid})
            except Exception:
                pass
        control_sessions.pop(sid, None)


# Not: /ws/agent/{id}, /ws/{room_id}/{peer_id} rotasından ÖNCE tanımlı olmalı; yoksa onun tarafından yutulur.
@app.websocket("/ws/{room_id}/{peer_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, peer_id: str):
    """Oda sinyalizasyon WebSocket'i (/ws/{room_id}/{peer_id}). Join token ile katılımcıyı doğrular. WebRTC offer, answer ve ICE mesajlarını hedef peer'e iletir; sohbet, medya durumu ve paylaşım olaylarını odaya yayınlar. Tanınmayan mesaj tipleri sessizce yok sayılır."""
    token = websocket.query_params.get("token", "")
    entry = validate_join_token(token)

    if not entry or entry["room_id"] != room_id or entry["peer_id"] != peer_id:
        await websocket.close(code=4001, reason="Geçersiz token")
        return

    name = entry["name"]
    await manager.connect(websocket, room_id, peer_id, name)

    existing_peers = manager.get_room_peers(room_id)

    await manager.send_to_peer(room_id, peer_id, {
        "type":         "room-joined",
        "peers":        [p for p in existing_peers if p["id"] != peer_id],
        "room_id":      room_id,
        "peer_id":      peer_id,
        "chat_history": manager.chat_history.get(room_id, []),  # Geçmiş mesajları gönder
    })

    await manager.broadcast_to_room(room_id, {
        "type":    "peer-joined",
        "peer_id": peer_id,
        "name":    name,
    }, exclude_peer=peer_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type  = data.get("type")
            target_id = data.get("target")

            # Mesaj tipini kısıtla — bilinmeyen tipler yoksay
            ALLOWED_TYPES = {
                "offer", "answer", "ice-candidate",
                "chat", "media-state",
                "screen-share-started", "screen-share-stopped",
                "recording-started", "recording-stopped",
                "file-chunk",
                "control-request", "control-response",
                "tts-audio",
            }
            if msg_type not in ALLOWED_TYPES:
                continue

            if msg_type in ["offer", "answer", "ice-candidate"]:
                if target_id:
                    await manager.send_to_peer(room_id, target_id, {
                        **data, "from": peer_id, "from_name": name
                    })

            elif msg_type == "chat":
                # Mesaj uzunluğunu sınırla
                message = str(data.get("message", ""))[:2000]
                chat_msg = {
                    "type":      "chat",
                    "from":      peer_id,
                    "from_name": name,
                    "message":   message,
                    "timestamp": data.get("timestamp"),
                }
                # Geçmişe ekle (max 50 mesaj)
                history = manager.chat_history.setdefault(room_id, [])
                history.append(chat_msg)
                if len(history) > 50:
                    history.pop(0)
                await manager.broadcast_to_room(room_id, chat_msg, exclude_peer=peer_id)

            elif msg_type in ["screen-share-started", "screen-share-stopped",
                              "recording-started", "recording-stopped"]:
                await manager.broadcast_to_room(room_id, {
                    **data, "from": peer_id, "from_name": name
                }, exclude_peer=peer_id)

            elif msg_type == "tts-audio":
                # Çevrilmiş sesi odadaki herkese gönder
                await manager.broadcast_to_room(room_id, {
                    "type": "tts-audio",
                    "audio_base64": data.get("audio_base64", ""),
                "text": data.get("text", ""),
                    "from": peer_id,
                    "from_name": name,
                }, exclude_peer=peer_id)

            elif msg_type == "media-state":
                await manager.broadcast_to_room(room_id, {
                    "type":  "media-state",
                    "from":  peer_id,
                    "audio": bool(data.get("audio")),
                    "video": bool(data.get("video")),
                }, exclude_peer=peer_id)

            elif msg_type == "file-chunk":
                if target_id:
                    await manager.send_to_peer(room_id, target_id, {
                        **data, "from": peer_id, "from_name": name
                    })

            elif msg_type == "control-request":
                target_peer = data.get("target_peer_id")
                session_id  = str(uuid.uuid4())
                control_sessions[session_id] = {
                    "room_id":            room_id,
                    "controller_peer_id": peer_id,
                    "target_peer_id":     target_peer,
                    "controller_name":    name,
                    "approved":           False,
                    "controller_ws":      None,
                    "agent_ws":           None,
                    "agent_id":           None,
                    "agent_key":          secrets.token_urlsafe(16),
                    "created_at":         time.time(),
                }
                await manager.send_to_peer(room_id, target_peer, {
                    "type":               "control-request",
                    "session_id":         session_id,
                    "agent_key":          control_sessions[session_id]["agent_key"],
                    "controller_peer_id": peer_id,
                    "controller_name":    name,
                })
                await manager.send_to_peer(room_id, peer_id, {
                    "type":       "control-session-created",
                    "session_id": session_id,
                })

            elif msg_type == "control-response":
                session_id = data.get("session_id")
                approved   = bool(data.get("approved", False))
                session    = control_sessions.get(session_id)
                if session and session["target_peer_id"] == peer_id:  # sadece hedef onaylayabilir
                    session["approved"] = approved
                    await manager.send_to_peer(room_id, session["controller_peer_id"], {
                        "type":       "control-response",
                        "session_id": session_id,
                        "approved":   approved,
                    })

    except WebSocketDisconnect:
        manager.disconnect(room_id, peer_id)
        await _peer_kontrol_oturumlarini_iptal_et(peer_id)
        await manager.broadcast_to_room(room_id, {
            "type":    "peer-left",
            "peer_id": peer_id,
            "name":    name,
        })
    except Exception as e:
        logger.error(f"WebSocket error for peer {peer_id}: {e}")
        manager.disconnect(room_id, peer_id)
        await _peer_kontrol_oturumlarini_iptal_et(peer_id)
        await manager.broadcast_to_room(room_id, {
            "type":    "peer-left",
            "peer_id": peer_id,
            "name":    name,
        })


# ─── WebSocket: Controller ────────────────────────────────────────────────────

@app.websocket("/ws/control/{session_id}/{controller_peer_id}")
async def control_endpoint(websocket: WebSocket, session_id: str, controller_peer_id: str):
    """Uzak kontrolcünün WebSocket'i (/ws/control/...). Yalnız kontrol oturumunu açan kişi ve onaylanmış oturum için çalışır. Fare ve klavye komutlarını ajana iletir. stop-control gelirse ya da bağlantı koparsa ajana durdurma mesajı gider."""
    token   = websocket.query_params.get("token", "")
    session = control_sessions.get(session_id)

    if not session:
        await websocket.close(code=4003, reason="Oturum bulunamadı")
        return

    # Sadece asıl kontrolcü bu endpoint'e bağlanabilir
    if session["controller_peer_id"] != controller_peer_id:
        await websocket.close(code=4003, reason="Yetkisiz erişim")
        return

    entry = validate_join_token(token)
    if (not entry or entry["room_id"] != session["room_id"]
            or entry["peer_id"] != controller_peer_id):
        await websocket.close(code=4001, reason="Geçersiz token")
        return

    await websocket.accept()
    session["controller_ws"] = websocket
    logger.info(f"Controller connected for session {session_id}")

    ALLOWED_CMDS = {
        "mouse-move", "mouse-click", "mouse-scroll",
        "key-press", "key-type", "mouse-down", "mouse-up",
        "stop-control",
    }

    try:
        while True:
            data     = await websocket.receive_json()
            msg_type = data.get("type")

            if not session.get("approved"):
                await websocket.send_json({"type": "error", "message": "İzin bekleniyor"})
                continue

            agent_ws = session.get("agent_ws")
            if not agent_ws:
                await websocket.send_json({"type": "error", "message": "Ajan bağlı değil"})
                continue

            if msg_type in ALLOWED_CMDS:
                if msg_type == "stop-control":
                    session["approved"] = False
                    try:
                        await agent_ws.send_json({"type": "stop-control", "session_id": session_id})
                    except Exception:
                        pass
                    break
                else:
                    try:
                        await agent_ws.send_json({**data, "session_id": session_id})
                    except Exception as e:
                        logger.error(f"Failed to forward command: {e}")

    except WebSocketDisconnect:
        logger.info(f"Controller disconnected for session {session_id}")
        agent_ws = session.get("agent_ws")
        if agent_ws:
            try:
                await agent_ws.send_json({"type": "stop-control", "session_id": session_id})
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Control endpoint error: {e}")


# ─── REST: Control ────────────────────────────────────────────────────────────

@app.post("/api/control/request")
@limiter.limit("10/minute")
async def request_control(request: Request, data: dict):
    """Uzak kontrol isteği başlatır. Yeni bir kontrol oturumu açar ve hedef peer odadaysa ona istek gönderir. Dönen sent alanı isteğin hedefe ulaşıp ulaşmadığını söyler."""
    token = data.get("token", "")
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")

    session_id        = str(uuid.uuid4())
    room_id           = entry["room_id"]
    controller_peer_id = entry["peer_id"]
    target_peer_id    = str(data.get("target_peer_id", ""))
    controller_name   = entry["name"]

    control_sessions[session_id] = {
        "room_id":            room_id,
        "controller_peer_id": controller_peer_id,
        "target_peer_id":     target_peer_id,
        "controller_name":    controller_name,
        "approved":           False,
        "controller_ws":      None,
        "agent_ws":           None,
        "agent_id":           None,
        "agent_key":          secrets.token_urlsafe(16),
        "created_at":         time.time(),
    }

    sent = False
    if room_id in manager.rooms and target_peer_id in manager.rooms[room_id]:
        await manager.send_to_peer(room_id, target_peer_id, {
            "type":               "control-request",
            "session_id":         session_id,
            "agent_key":          control_sessions[session_id]["agent_key"],
            "controller_peer_id": controller_peer_id,
            "controller_name":    controller_name,
        })
        sent = True

    return {"session_id": session_id, "sent": sent}


@app.post("/api/control/respond")
async def respond_control(data: dict):
    """Hedef peer'in kontrol isteğine onay ya da red verdiği uç. Yalnız oturumun hedef peer'i çağırabilir; başkası çağırırsa 403 döner."""
    token   = data.get("token", "")
    entry   = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")

    session_id = data.get("session_id")
    approved   = bool(data.get("approved", False))
    session    = control_sessions.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Oturum bulunamadı")

    # Sadece hedef peer onaylayabilir
    if entry["peer_id"] != session["target_peer_id"]:
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")

    session["approved"] = approved
    await manager.send_to_peer(session["room_id"], session["controller_peer_id"], {
        "type":       "control-response",
        "session_id": session_id,
        "approved":   approved,
    })
    return {"ok": True}


@app.post("/api/control/stop")
async def stop_control(data: dict):
    """Kontrol oturumunu sonlandırır. Yalnız kontrolcü ya da hedef peer durdurabilir. Oturum yoksa da başarılı yanıt döner."""
    token = data.get("token", "")
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")

    session_id = data.get("session_id")
    session    = control_sessions.get(session_id)

    if session:
        # Sadece kontrolcü veya hedef durdurabilir. Yetki yoksa oturum silinmez.
        if entry["peer_id"] not in (session["controller_peer_id"], session["target_peer_id"]):
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")
        control_sessions.pop(session_id, None)
        for ws_key in ["controller_ws", "agent_ws"]:
            ws = session.get(ws_key)
            if ws:
                try:
                    await ws.send_json({"type": "stop-control", "session_id": session_id})
                except Exception:
                    pass

    return {"ok": True}


# ─── Static Files (EN SONA) ───────────────────────────────────────────────────

# ─── TTS Proxy ───────────────────────────────────────────────────────────────
import httpx

TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "")
TTS_API_KEY = os.getenv("TTS_API_KEY", "")

async def _tts_istek(method: str, path: str, timeout: float, **kwargs):
    """TTS servisine istek at; hata/bozuk yanıtta anlamlı HTTP hatası dön."""
    if not TTS_SERVICE_URL:
        raise HTTPException(status_code=503, detail="TTS servisi yapılandırılmamış.")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method, f"{TTS_SERVICE_URL}{path}",
                headers={"x-api-key": TTS_API_KEY}, **kwargs,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="TTS servisi zaman aşımına uğradı.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="TTS servisine ulaşılamadı.")
    if response.status_code >= 400:
        logger.error(f"TTS {path} -> {response.status_code}: {response.text[:200]}")
        raise HTTPException(status_code=502, detail=f"TTS servisi hata verdi ({response.status_code}).")
    try:
        return response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="TTS servisi geçersiz yanıt döndü.")


@app.post("/api/tts/synthesize")
@limiter.limit("30/minute")
async def tts_synthesize(request: Request, data: dict):
    """Çevrilmiş metni TTS servisine gönderip sentezlenmiş sesi döner. Yalnız geçerli join token ile çalışır. Zaman aşımı 30 saniyedir."""
    token = data.get("token", "")
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")
    return await _tts_istek("POST", "/synthesize", 30.0, json={
        "audio_base64": data.get("audio_base64", ""),
        "text": data.get("text", ""),
        "peer_id": entry["peer_id"],
        "source_lang": data.get("source_lang", "tr"),
        "target_lang": data.get("target_lang", "en"),
        "session_id": data.get("session_id"),
    })

@app.post("/api/tts/voice-profile")
@limiter.limit("5/minute")
async def tts_voice_profile(request: Request, data: dict):
    """Kişinin kendi sesinden ses profili çıkarmak için TTS servisine istek atar. İşlem ağır olduğundan dakikada 5 istekle sınırlıdır ve zaman aşımı 60 saniyedir. Canlı kurulumda ses klonlama kullanılmıyor; bu ucun servis tarafında karşılığı olmayabilir."""
    token = data.get("token", "")
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")
    return await _tts_istek("POST", "/voice-profile", 60.0, json={
        "audio_base64": data.get("audio_base64", ""),
        "text": data.get("text", ""),
        "peer_id": entry["peer_id"],
    })

@app.get("/api/tts/voice-profile/status")
async def tts_voice_profile_status(request: Request, token: str):
    """Ses profilinin hazır olup olmadığını TTS servisinden sorgular. Profil yalnız token sahibinin peer_id değerine göre aranır."""
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")
    return await _tts_istek("GET", f"/voice-profile/{entry['peer_id']}", 10.0)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("HOST", "0.0.0.0"),
                port=int(os.getenv("PORT", "8000")), reload=True)
