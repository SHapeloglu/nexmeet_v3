import json
import uuid
import logging
import os
import time
import secrets
import mimetypes
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect,
    UploadFile, File, Form, HTTPException,
    Depends, Header, Request
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import asyncio
import aiofiles

# ─── Config ──────────────────────────────────────────────────────────────────
load_dotenv()

SECRET_KEY    = os.getenv("SECRET_KEY", secrets.token_hex(32))
RAW_ORIGINS   = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000")
ALLOWED_ORIGINS = [o.strip() for o in RAW_ORIGINS.split(",") if o.strip()]
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "100")) * 1024 * 1024

# İzin verilen MIME tipleri (executable türler yasaklı)
ALLOWED_MIME_TYPES = {
    # Dokümanlar
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain", "text/csv",
    # Görseller
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    # Ses / Video
    "audio/mpeg", "audio/ogg", "audio/wav", "video/mp4", "video/webm",
    # Sıkıştırma
    "application/zip", "application/x-zip-compressed",
}

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".msi",
    ".dll", ".so", ".dylib", ".bin", ".com", ".scr",
    ".vbs", ".js", ".jar", ".py", ".php", ".rb",
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Rate Limiter ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="NexMeet")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

# ─── In-memory state ─────────────────────────────────────────────────────────
shared_files:    Dict[str, dict] = {}
control_sessions: Dict[str, dict] = {}
agent_connections: Dict[str, WebSocket] = {}

# ─── Join token'ları (oda başına basit token) ─────────────────────────────────
# token -> {room_id, peer_id, name, expires_at}
join_tokens: Dict[str, dict] = {}


def generate_join_token(room_id: str, peer_id: str, name: str) -> str:
    """Oda bağlantısı için kısa süreli token oluştur."""
    token = secrets.token_urlsafe(32)
    join_tokens[token] = {
        "room_id": room_id,
        "peer_id": peer_id,
        "name": name,
        "expires_at": time.time() + 3600,  # 1 saat geçerli
    }
    return token


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
    expired = [t for t, v in join_tokens.items() if now > v["expires_at"]]
    for t in expired:
        del join_tokens[t]


def validate_file(filename: str, content_type: str, content: bytes) -> str:
    """
    Dosya türünü ve uzantısını doğrula.
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

    # Content-type doğrulaması
    detected = mimetypes.guess_type(safe_name)[0] or content_type or "application/octet-stream"
    if detected not in ALLOWED_MIME_TYPES and content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Bu dosya türü desteklenmiyor."
        )

    return safe_name


# ─── Connection Manager ───────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.rooms: Dict[str, Dict[str, WebSocket]] = {}
        self.peer_names: Dict[str, str] = {}
        # Son 50 sohbet mesajını oda bazında sakla
        self.chat_history: Dict[str, list] = {}

    async def connect(self, websocket: WebSocket, room_id: str, peer_id: str, name: str):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
            self.chat_history[room_id] = []
        self.rooms[room_id][peer_id] = websocket
        self.peer_names[peer_id] = name
        logger.info(f"Peer {peer_id} ({name}) joined room {room_id}")

    def disconnect(self, room_id: str, peer_id: str):
        if room_id in self.rooms:
            self.rooms[room_id].pop(peer_id, None)
            if not self.rooms[room_id]:
                del self.rooms[room_id]
                self.chat_history.pop(room_id, None)  # Oda boşaldı, geçmişi temizle
        self.peer_names.pop(peer_id, None)
        logger.info(f"Peer {peer_id} left room {room_id}")

    async def send_to_peer(self, room_id: str, peer_id: str, message: dict):
        if room_id in self.rooms and peer_id in self.rooms[room_id]:
            try:
                await self.rooms[room_id][peer_id].send_json(message)
            except Exception as e:
                logger.error(f"Error sending to peer {peer_id}: {e}")

    async def broadcast_to_room(self, room_id: str, message: dict, exclude_peer: str = None):
        if room_id not in self.rooms:
            return
        for peer_id, ws in list(self.rooms[room_id].items()):
            if peer_id != exclude_peer:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to peer {peer_id}: {e}")

    def get_room_peers(self, room_id: str) -> list:
        if room_id not in self.rooms:
            return []
        return [
            {"id": pid, "name": self.peer_names.get(pid, "Unknown")}
            for pid in self.rooms[room_id].keys()
        ]


manager = ConnectionManager()


# ─── HTTP Endpoints ───────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/room/{room_id}")
async def get_room(room_id: str):
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/room/{room_id}/info")
async def room_info(room_id: str):
    peers = manager.get_room_peers(room_id)
    return {"room_id": room_id, "peer_count": len(peers), "peers": peers}


@app.post("/api/join-token")
@limiter.limit("20/minute")
async def create_join_token(request: Request, data: dict):
    """
    Oda katılım token'ı oluştur.
    Frontend bu token'ı alır ve WS bağlantısında kullanır.
    """
    name    = str(data.get("name", "")).strip()[:50]
    room_id = str(data.get("room_id", "")).strip()[:20]
    peer_id = str(data.get("peer_id", "")).strip()[:30]

    if not name or not room_id or not peer_id:
        raise HTTPException(status_code=400, detail="name, room_id ve peer_id zorunlu.")

    cleanup_expired_tokens()
    token = generate_join_token(room_id, peer_id, name)
    return {"token": token}


@app.post("/api/upload/{room_id}")
@limiter.limit("10/minute")
async def upload_file(
    request: Request,
    room_id: str,
    file: UploadFile = File(...),
    peer_id: str = Form(...),
    uploader_name: str = Form(...),
    token: str = Form(...),
):
    """Dosya yükle — token doğrulaması zorunlu."""
    # Token doğrula
    entry = validate_join_token(token)
    if not entry or entry["room_id"] != room_id or entry["peer_id"] != peer_id:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş token.")

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
    return {"file_id": file_id, "name": safe_name}


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

    return FileResponse(meta["path"], filename=meta["name"], media_type=meta["type"])


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

@app.websocket("/ws/{room_id}/{peer_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, peer_id: str):
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
                    "audio_base64": data.get("audio_base64"),
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
                }
                await manager.send_to_peer(room_id, target_peer, {
                    "type":               "control-request",
                    "session_id":         session_id,
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
        await manager.broadcast_to_room(room_id, {
            "type":    "peer-left",
            "peer_id": peer_id,
            "name":    name,
        })
    except Exception as e:
        logger.error(f"WebSocket error for peer {peer_id}: {e}")
        manager.disconnect(room_id, peer_id)


# ─── WebSocket: Agent ─────────────────────────────────────────────────────────

@app.websocket("/ws/agent/{agent_id}")
async def agent_endpoint(websocket: WebSocket, agent_id: str):
    token      = websocket.query_params.get("token", "")
    session_id = websocket.query_params.get("session_id", "")
    session    = control_sessions.get(session_id)

    # Agent doğrulama: session gerçek mi ve token oda token'ı ile örtüşüyor mu?
    if not session:
        await websocket.close(code=4001, reason="Geçersiz session")
        return

    entry = validate_join_token(token)
    if not entry or entry["room_id"] != session["room_id"]:
        await websocket.close(code=4001, reason="Geçersiz token")
        return

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


# ─── WebSocket: Controller ────────────────────────────────────────────────────

@app.websocket("/ws/control/{session_id}/{controller_peer_id}")
async def control_endpoint(websocket: WebSocket, session_id: str, controller_peer_id: str):
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
    if not entry or entry["room_id"] != session["room_id"]:
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
    }

    sent = False
    if room_id in manager.rooms and target_peer_id in manager.rooms[room_id]:
        await manager.send_to_peer(room_id, target_peer_id, {
            "type":               "control-request",
            "session_id":         session_id,
            "controller_peer_id": controller_peer_id,
            "controller_name":    controller_name,
        })
        sent = True

    return {"session_id": session_id, "sent": sent}


@app.post("/api/control/respond")
async def respond_control(data: dict):
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
    token = data.get("token", "")
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")

    session_id = data.get("session_id")
    session    = control_sessions.pop(session_id, None)

    if session:
        # Sadece kontrolcü veya hedef durdurabilir
        if entry["peer_id"] not in (session["controller_peer_id"], session["target_peer_id"]):
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")
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

@app.post("/api/tts/synthesize")
@limiter.limit("30/minute")
async def tts_synthesize(request: Request, data: dict):
    token = data.get("token", "")
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")
    if not TTS_SERVICE_URL:
        raise HTTPException(status_code=503, detail="TTS servisi yapılandırılmamış.")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{TTS_SERVICE_URL}/synthesize",
            json={
                "audio_base64": data.get("audio_base64"),
                "peer_id": entry["peer_id"],
                "source_lang": data.get("source_lang", "tr"),
                "target_lang": data.get("target_lang", "en"),
                "session_id": data.get("session_id"),
            },
            headers={"x-api-key": TTS_API_KEY},
        )
        return response.json()

@app.post("/api/tts/voice-profile")
@limiter.limit("5/minute")
async def tts_voice_profile(request: Request, data: dict):
    token = data.get("token", "")
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{TTS_SERVICE_URL}/voice-profile",
            json={
                "audio_base64": data.get("audio_base64"),
                "peer_id": entry["peer_id"],
            },
            headers={"x-api-key": TTS_API_KEY},
        )
        return response.json()

@app.get("/api/tts/voice-profile/status")
async def tts_voice_profile_status(request: Request, token: str):
    entry = validate_join_token(token)
    if not entry:
        raise HTTPException(status_code=401, detail="Geçersiz token.")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{TTS_SERVICE_URL}/voice-profile/{entry['peer_id']}",
            headers={"x-api-key": TTS_API_KEY},
        )
        return response.json()

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("HOST", "0.0.0.0"),
                port=int(os.getenv("PORT", "8000")), reload=True)
