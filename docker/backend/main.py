import json
import uuid
import logging
import os
import time
import base64
from pathlib import Path
from typing import Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import aiofiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="VideoConference App")

# Absolute paths — çalışma dizininden bağımsız
BASE_DIR     = Path(__file__).parent.parent   # VideoConference/
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR  = BASE_DIR / "uploads"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
UPLOADS_DIR.mkdir(exist_ok=True)

# In-memory file registry
shared_files: Dict[str, dict] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Room management
rooms: Dict[str, Dict[str, WebSocket]] = {}  # room_id -> {peer_id -> websocket}
room_hosts: Dict[str, str] = {}  # room_id -> host peer_id


class ConnectionManager:
    def __init__(self):
        self.rooms: Dict[str, Dict[str, WebSocket]] = {}
        self.peer_names: Dict[str, str] = {}  # peer_id -> display name

    async def connect(self, websocket: WebSocket, room_id: str, peer_id: str, name: str):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
        self.rooms[room_id][peer_id] = websocket
        self.peer_names[peer_id] = name
        logger.info(f"Peer {peer_id} ({name}) joined room {room_id}")

    def disconnect(self, room_id: str, peer_id: str):
        if room_id in self.rooms:
            self.rooms[room_id].pop(peer_id, None)
            if not self.rooms[room_id]:
                del self.rooms[room_id]
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


@app.post("/api/upload/{room_id}")
async def upload_file(
    room_id: str,
    file: UploadFile = File(...),
    peer_id: str = Form(...),
    uploader_name: str = Form(...)
):
    """Upload a file and notify room participants."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Dosya çok büyük (max 100 MB)")

    file_id = str(uuid.uuid4())
    safe_name = os.path.basename(file.filename or "file")
    save_path = str(UPLOADS_DIR / f"{file_id}_{safe_name}")

    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    meta = {
        "file_id": file_id,
        "name": safe_name,
        "size": len(content),
        "type": file.content_type or "application/octet-stream",
        "uploader": uploader_name,
        "peer_id": peer_id,
        "room_id": room_id,
        "path": save_path,
        "timestamp": time.strftime("%H:%M")
    }
    shared_files[file_id] = meta

    # Notify all peers in room
    await manager.broadcast_to_room(room_id, {
        "type": "file-shared",
        "file_id": file_id,
        "name": safe_name,
        "size": len(content),
        "mime_type": meta["type"],
        "uploader": uploader_name,
        "timestamp": meta["timestamp"]
    })

    logger.info(f"File uploaded: {safe_name} ({len(content)} bytes) by {uploader_name} in {room_id}")
    return {"file_id": file_id, "name": safe_name}


@app.get("/api/download/{file_id}")
async def download_file(file_id: str):
    """Download a shared file."""
    meta = shared_files.get(file_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    if not os.path.exists(meta["path"]):
        raise HTTPException(status_code=404, detail="Dosya sunucudan silinmiş")
    return FileResponse(
        meta["path"],
        filename=meta["name"],
        media_type=meta["type"]
    )


@app.get("/api/room/{room_id}/files")
async def room_files(room_id: str):
    """List files shared in a room."""
    files = [
        {k: v for k, v in m.items() if k != "path"}
        for m in shared_files.values()
        if m["room_id"] == room_id
    ]
    return {"files": files}


@app.websocket("/ws/{room_id}/{peer_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, peer_id: str):
    name = websocket.query_params.get("name", f"User-{peer_id[:6]}")
    await manager.connect(websocket, room_id, peer_id, name)

    existing_peers = manager.get_room_peers(room_id)

    # Notify this peer about existing peers
    await manager.send_to_peer(room_id, peer_id, {
        "type": "room-joined",
        "peers": [p for p in existing_peers if p["id"] != peer_id],
        "room_id": room_id,
        "peer_id": peer_id
    })

    # Notify existing peers about new peer
    await manager.broadcast_to_room(room_id, {
        "type": "peer-joined",
        "peer_id": peer_id,
        "name": name
    }, exclude_peer=peer_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            target_id = data.get("target")

            logger.info(f"Message from {peer_id} in {room_id}: {msg_type} -> {target_id}")

            if msg_type in ["offer", "answer", "ice-candidate"]:
                # Forward WebRTC signaling to target peer
                if target_id:
                    await manager.send_to_peer(room_id, target_id, {
                        **data,
                        "from": peer_id,
                        "from_name": name
                    })

            elif msg_type == "chat":
                # Broadcast chat message to all in room
                await manager.broadcast_to_room(room_id, {
                    "type": "chat",
                    "from": peer_id,
                    "from_name": name,
                    "message": data.get("message", ""),
                    "timestamp": data.get("timestamp")
                }, exclude_peer=peer_id)

            elif msg_type == "screen-share-started":
                await manager.broadcast_to_room(room_id, {
                    "type": "screen-share-started",
                    "from": peer_id,
                    "from_name": name
                }, exclude_peer=peer_id)

            elif msg_type == "screen-share-stopped":
                await manager.broadcast_to_room(room_id, {
                    "type": "screen-share-stopped",
                    "from": peer_id
                }, exclude_peer=peer_id)

            elif msg_type == "media-state":
                await manager.broadcast_to_room(room_id, {
                    "type": "media-state",
                    "from": peer_id,
                    "audio": data.get("audio"),
                    "video": data.get("video")
                }, exclude_peer=peer_id)

            elif msg_type == "recording-started":
                await manager.broadcast_to_room(room_id, {
                    "type": "recording-started",
                    "from": peer_id,
                    "from_name": name
                }, exclude_peer=peer_id)

            elif msg_type == "recording-stopped":
                await manager.broadcast_to_room(room_id, {
                    "type": "recording-stopped",
                    "from": peer_id
                }, exclude_peer=peer_id)

            elif msg_type == "file-chunk":
                # P2P file transfer signaling (for large files via DataChannel)
                if target_id:
                    await manager.send_to_peer(room_id, target_id, {
                        **data,
                        "from": peer_id,
                        "from_name": name
                    })

            elif msg_type == "control-request":
                # Uzak kontrol isteği — hedef peer'a ilet
                target_id = data.get("target_peer_id")
                import uuid as _uuid
                session_id = str(_uuid.uuid4())
                control_sessions[session_id] = {
                    "room_id": room_id,
                    "controller_peer_id": peer_id,
                    "target_peer_id": target_id,
                    "controller_name": name,
                    "approved": False,
                    "controller_ws": None,
                    "agent_ws": None,
                    "agent_id": None,
                }
                logger.info(f"Control request: {peer_id} -> {target_id}, session={session_id}")
                await manager.send_to_peer(room_id, target_id, {
                    "type": "control-request",
                    "session_id": session_id,
                    "controller_peer_id": peer_id,
                    "controller_name": name,
                })
                # Kontrolcüye session_id gönder
                await manager.send_to_peer(room_id, peer_id, {
                    "type": "control-session-created",
                    "session_id": session_id,
                })

            elif msg_type == "control-response":
                # Hedef peer'ın cevabı — kontrolcüye ilet
                session_id = data.get("session_id")
                approved = data.get("approved", False)
                session = control_sessions.get(session_id)
                if session:
                    session["approved"] = approved
                    await manager.send_to_peer(room_id, session["controller_peer_id"], {
                        "type": "control-response",
                        "session_id": session_id,
                        "approved": approved,
                    })

    except WebSocketDisconnect:
        manager.disconnect(room_id, peer_id)
        await manager.broadcast_to_room(room_id, {
            "type": "peer-left",
            "peer_id": peer_id,
            "name": name
        })
    except Exception as e:
        logger.error(f"WebSocket error for peer {peer_id}: {e}")
        manager.disconnect(room_id, peer_id)


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# ─── Remote Control ──────────────────────────────────────────────────────────
# active_control_sessions: session_id -> {controller_ws, agent_ws, room_id, approved}
control_sessions: Dict[str, dict] = {}
# agent connections: agent_id -> websocket
agent_connections: Dict[str, WebSocket] = {}


@app.websocket("/ws/agent/{agent_id}")
async def agent_endpoint(websocket: WebSocket, agent_id: str):
    """Python agent connects here to receive control commands and send screen frames."""
    await websocket.accept()
    agent_connections[agent_id] = websocket
    logger.info(f"Agent connected: {agent_id}")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            session_id = data.get("session_id")

            if msg_type == "frame":
                # Forward screen frame to controller
                session = control_sessions.get(session_id)
                if session and session.get("approved") and session.get("controller_ws"):
                    try:
                        await session["controller_ws"].send_json({
                            "type": "remote-frame",
                            "session_id": session_id,
                            "frame": data.get("frame"),  # base64 jpeg
                            "width": data.get("width"),
                            "height": data.get("height"),
                        })
                    except Exception:
                        pass

            elif msg_type == "agent-ready":
                # Agent confirmed session
                session = control_sessions.get(session_id)
                if session:
                    session["agent_ws"] = websocket
                    session["agent_id"] = agent_id

    except WebSocketDisconnect:
        agent_connections.pop(agent_id, None)
        # Clean up sessions for this agent
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


@app.websocket("/ws/control/{session_id}/{controller_peer_id}")
async def control_endpoint(websocket: WebSocket, session_id: str, controller_peer_id: str):
    """Controller (browser) sends mouse/keyboard events here."""
    await websocket.accept()
    session = control_sessions.get(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "Oturum bulunamadı"})
        await websocket.close()
        return

    session["controller_ws"] = websocket
    logger.info(f"Controller connected for session {session_id}")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if not session.get("approved"):
                await websocket.send_json({"type": "error", "message": "İzin bekleniyor"})
                continue

            agent_ws = session.get("agent_ws")
            if not agent_ws:
                await websocket.send_json({"type": "error", "message": "Ajan bağlı değil"})
                continue

            # Forward control commands to agent
            if msg_type in ["mouse-move", "mouse-click", "mouse-scroll",
                            "key-press", "key-type", "mouse-down", "mouse-up"]:
                try:
                    await agent_ws.send_json({**data, "session_id": session_id})
                except Exception as e:
                    logger.error(f"Failed to forward command: {e}")

            elif msg_type == "stop-control":
                session["approved"] = False
                agent_ws2 = session.get("agent_ws")
                if agent_ws2:
                    await agent_ws2.send_json({"type": "stop-control", "session_id": session_id})
                break

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


@app.post("/api/control/request")
async def request_control(data: dict):
    """Browser requests remote control of a peer."""
    session_id = str(uuid.uuid4())
    room_id = data.get("room_id")
    controller_peer_id = data.get("controller_peer_id")
    target_peer_id = data.get("target_peer_id")
    controller_name = data.get("controller_name")

    control_sessions[session_id] = {
        "room_id": room_id,
        "controller_peer_id": controller_peer_id,
        "target_peer_id": target_peer_id,
        "controller_name": controller_name,
        "approved": False,
        "controller_ws": None,
        "agent_ws": None,
        "agent_id": None,
    }

    # Debug: log room state
    peers_in_room = list(manager.rooms.get(room_id, {}).keys())
    logger.info(f"Control request: room={room_id}, target={target_peer_id}, peers_in_room={peers_in_room}")

    # Notify the target peer via room WS
    sent = False
    if room_id in manager.rooms and target_peer_id in manager.rooms[room_id]:
        await manager.send_to_peer(room_id, target_peer_id, {
            "type": "control-request",
            "session_id": session_id,
            "controller_peer_id": controller_peer_id,
            "controller_name": controller_name,
        })
        sent = True
        logger.info(f"Control request sent to {target_peer_id}")
    else:
        logger.warning(f"Target peer {target_peer_id} not found in room {room_id}")

    return {"session_id": session_id, "sent": sent, "peers_in_room": peers_in_room}


@app.post("/api/control/respond")
async def respond_control(data: dict):
    """Target peer accepts or rejects control request."""
    session_id = data.get("session_id")
    approved = data.get("approved", False)
    session = control_sessions.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Oturum bulunamadı")

    session["approved"] = approved
    controller_peer_id = session["controller_peer_id"]
    room_id = session["room_id"]

    await manager.send_to_peer(room_id, controller_peer_id, {
        "type": "control-response",
        "session_id": session_id,
        "approved": approved,
    })

    return {"ok": True}


@app.post("/api/control/stop")
async def stop_control(data: dict):
    """Stop a control session."""
    session_id = data.get("session_id")
    session = control_sessions.pop(session_id, None)
    if session:
        for ws_key in ["controller_ws", "agent_ws"]:
            ws = session.get(ws_key)
            if ws:
                try:
                    await ws.send_json({"type": "stop-control", "session_id": session_id})
                except Exception:
                    pass
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
