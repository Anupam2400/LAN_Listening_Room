"""
LAN Listening Room — backend v2

Multi-source: YouTube, Spotify embeds, local audio uploads.
Features: song queue, real-time chat, co-host system, song recommendations, yt-dlp fallback.

Run:
    pip install -r requirements.txt
    python main.py

Host panel:  http://<lan-ip>:8000/host?key=<HOST_KEY printed in console>
Guest link:  http://<lan-ip>:8000/join
"""
import asyncio
import json
import re
import secrets
import socket
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
UPLOADS_DIR = APP_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

BAN_LIST_PATH = APP_DIR / "banned_guests.json"

HOST_KEY = secrets.token_urlsafe(9)

app = FastAPI()

# Optional yt-dlp for restricted video fallback
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False


# ---------------------------------------------------------------------------
# Room State
# ---------------------------------------------------------------------------
class Room:
    def __init__(self):
        self.host_ws: Optional[WebSocket] = None
        # token -> {name, ws, status: "pending"|"admitted"|"banned", role: "guest"|"cohost"}
        self.guests: dict[str, dict] = {}

        self.now_playing = {
            "source": None,       # "youtube" | "spotify" | "local"
            "videoId": None,      # YouTube video ID
            "spotifyUri": None,   # Spotify embed URL
            "fileUrl": None,      # Local /uploads/... URL
            "title": None,
            "isPlaying": False,
            "position": 0.0,
            "updatedAt": time.time(),
        }

        self.queue: list[dict] = []
        # [{id, source, url, title, addedBy}]

        self.chat: list[dict] = []
        # [{sender, text, timestamp, role}]  or if encrypted: {sender, data, timestamp, role, encrypted: True}

        self.song_requests: list[dict] = []
        # [{id, token, name, source, url, title, timestamp}]

    def guest_public_list(self):
        return [
            {
                "token": t,
                "name": g["name"],
                "status": g["status"],
                "role": g.get("role", "guest"),
                "online": g["ws"] is not None,
            }
            for t, g in self.guests.items()
        ]


# ---------------------------------------------------------------------------
# Persistent Ban List
# ---------------------------------------------------------------------------
def load_ban_list() -> dict[str, dict]:
    """Load ban list from JSON file. Returns {token: {name, bannedAt}}."""
    if not BAN_LIST_PATH.exists():
        return {}
    try:
        data = json.loads(BAN_LIST_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_ban_list(ban_list: dict[str, dict]):
    """Persist the ban list to disk."""
    BAN_LIST_PATH.write_text(json.dumps(ban_list, indent=2))


# In-memory mirror of the persisted ban list  {token -> {name, bannedAt}}
_ban_list: dict[str, dict] = load_ban_list()

room = Room()

# Stamp any tokens already in the ban file into room.guests so
# reconnect detection works even across server restarts.
for _tok, _entry in _ban_list.items():
    room.guests[_tok] = {
        "name": _entry.get("name", "Guest"),
        "ws": None,
        "status": "banned",
        "role": "guest",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def estimated_position():
    np = room.now_playing
    if not np["isPlaying"] or np["source"] is None:
        return np["position"]
    elapsed = time.time() - np["updatedAt"]
    return np["position"] + elapsed


def make_sync_payload():
    np = room.now_playing
    return {
        "type": "sync",
        "source": np["source"],
        "videoId": np["videoId"],
        "spotifyUri": np["spotifyUri"],
        "fileUrl": np["fileUrl"],
        "title": np["title"],
        "isPlaying": np["isPlaying"],
        "position": estimated_position(),
    }


def make_queue_payload():
    return {"type": "queue_update", "queue": room.queue}


def make_room_state_payload():
    return {
        "type": "room_state",
        "guests": room.guest_public_list(),
        "requests": room.song_requests,
    }


async def broadcast_to_all(payload: dict):
    """Send to host and all admitted guests."""
    if room.host_ws:
        try:
            await room.host_ws.send_json(payload)
        except Exception:
            pass
    for g in room.guests.values():
        if g["status"] == "admitted" and g["ws"]:
            try:
                await g["ws"].send_json(payload)
            except Exception:
                pass


async def push_to_host(payload: dict):
    if room.host_ws:
        try:
            await room.host_ws.send_json(payload)
        except Exception:
            pass


async def push_to_guest(token: str, payload: dict):
    g = room.guests.get(token)
    if g and g["ws"]:
        try:
            await g["ws"].send_json(payload)
        except Exception:
            pass


async def push_room_state_to_host():
    await push_to_host(make_room_state_payload())


# ---------------------------------------------------------------------------
# Shared playback action handler (host + co-host)
# ---------------------------------------------------------------------------
async def handle_playback_action(action: str, msg: dict):
    if action == "set_video":
        room.now_playing.update({
            "source": "youtube", "videoId": msg["videoId"],
            "spotifyUri": None, "fileUrl": None,
            "title": msg.get("title"),
            "isPlaying": True, "position": 0.0, "updatedAt": time.time(),
        })
        await broadcast_to_all(make_sync_payload())

    elif action == "set_spotify":
        room.now_playing.update({
            "source": "spotify", "videoId": None,
            "spotifyUri": msg["spotifyUri"], "fileUrl": None,
            "title": msg.get("title"),
            "isPlaying": True, "position": 0.0, "updatedAt": time.time(),
        })
        await broadcast_to_all(make_sync_payload())

    elif action == "set_local":
        room.now_playing.update({
            "source": "local", "videoId": None,
            "spotifyUri": None, "fileUrl": msg["fileUrl"],
            "title": msg.get("title"),
            "isPlaying": True, "position": 0.0, "updatedAt": time.time(),
        })
        await broadcast_to_all(make_sync_payload())

    elif action in ("play", "pause", "seek"):
        if action == "play":
            room.now_playing["isPlaying"] = True
        elif action == "pause":
            room.now_playing["isPlaying"] = False
        if "position" in msg:
            room.now_playing["position"] = msg["position"]
        room.now_playing["updatedAt"] = time.time()
        await broadcast_to_all(make_sync_payload())

    elif action == "queue_add":
        room.queue.append({
            "id": str(uuid.uuid4()),
            "source": msg.get("source", "youtube"),
            "url": msg.get("url", ""),
            "title": msg.get("title", "Unknown"),
            "addedBy": msg.get("addedBy", "Host"),
        })
        await broadcast_to_all(make_queue_payload())

    elif action == "queue_remove":
        idx = msg.get("index", -1)
        if 0 <= idx < len(room.queue):
            room.queue.pop(idx)
            await broadcast_to_all(make_queue_payload())

    elif action == "queue_reorder":
        frm, to = msg.get("from", -1), msg.get("to", -1)
        if 0 <= frm < len(room.queue) and 0 <= to < len(room.queue) and frm != to:
            item = room.queue.pop(frm)
            room.queue.insert(to, item)
            await broadcast_to_all(make_queue_payload())

    elif action == "queue_next":
        if room.queue:
            nxt = room.queue.pop(0)
            source_map = {
                "youtube": {"source": "youtube", "videoId": nxt["url"], "spotifyUri": None, "fileUrl": None},
                "spotify": {"source": "spotify", "videoId": None, "spotifyUri": nxt["url"], "fileUrl": None},
                "local":   {"source": "local",   "videoId": None, "spotifyUri": None, "fileUrl": nxt["url"]},
            }
            updates = source_map.get(nxt["source"], source_map["youtube"])
            room.now_playing.update({
                **updates, "title": nxt["title"],
                "isPlaying": True, "position": 0.0, "updatedAt": time.time(),
            })
            await broadcast_to_all(make_sync_payload())
            await broadcast_to_all(make_queue_payload())


# ---------------------------------------------------------------------------
# HTTP Routes
# ---------------------------------------------------------------------------
@app.get("/join", response_class=HTMLResponse)
async def join_page():
    return FileResponse(STATIC_DIR / "guest.html")


@app.get("/host", response_class=HTMLResponse)
async def host_page(key: str = Query(default="")):
    if key != HOST_KEY:
        return HTMLResponse("<h1>Not authorized</h1><p>Missing or incorrect host key.</p>", status_code=403)
    return FileResponse(STATIC_DIR / "host.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


@app.get("/api/ban-list")
async def api_ban_list(key: str = Query(default="")):
    """Return the current ban list. Host-only."""
    if key != HOST_KEY:
        return JSONResponse({"error": "Not authorized"}, status_code=403)
    return JSONResponse(
        [
            {"token": tok, "name": entry.get("name", "Guest"), "bannedAt": entry.get("bannedAt")}
            for tok, entry in _ban_list.items()
        ]
    )


@app.delete("/api/unban/{token}")
async def api_unban(token: str, key: str = Query(default="")):
    """Remove a guest from the ban list. Host-only."""
    if key != HOST_KEY:
        return JSONResponse({"error": "Not authorized"}, status_code=403)
    if token not in _ban_list:
        return JSONResponse({"error": "Token not in ban list"}, status_code=404)
    _ban_list.pop(token, None)
    save_ban_list(_ban_list)
    # Also clear the in-memory guest entry so they can rejoin
    room.guests.pop(token, None)
    return JSONResponse({"ok": True, "token": token})


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    ALLOWED = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".opus", ".webm"}
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED:
        return JSONResponse({"error": "File type not allowed"}, status_code=400)
    safe_name = f"{uuid.uuid4()}{ext}"
    dest = UPLOADS_DIR / safe_name
    dest.write_bytes(await file.read())
    return {"url": f"/uploads/{safe_name}", "title": Path(file.filename).stem}


@app.get("/api/yt-audio")
async def yt_audio(videoId: str = Query(...)):
    if not YT_DLP_AVAILABLE:
        return JSONResponse({"error": "yt-dlp not installed on server"}, status_code=503)
    url = f"https://www.youtube.com/watch?v={videoId}"
    ydl_opts = {"format": "bestaudio/best", "quiet": True, "no_warnings": True}
    try:
        loop = asyncio.get_event_loop()
        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                fmts = info.get("formats", [])
                audio = [f for f in fmts if f.get("acodec") != "none" and f.get("vcodec") == "none"]
                best = max(audio or fmts, key=lambda f: f.get("abr", 0) or 0)
                return {"streamUrl": best["url"], "title": info.get("title", "")}
        return await loop.run_in_executor(None, extract)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Host WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws/host")
async def ws_host(websocket: WebSocket, key: str = Query(default="")):
    if key != HOST_KEY:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    room.host_ws = websocket

    # Send full initial state
    await push_room_state_to_host()
    await websocket.send_json(make_sync_payload())
    await websocket.send_json(make_queue_payload())
    await websocket.send_json({"type": "chat_history", "messages": room.chat[-100:]})

    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            action = msg.get("action")

            if action == "admit":
                g = room.guests.get(msg.get("token"))
                if g:
                    g["status"] = "admitted"
                    if g["ws"]:
                        await g["ws"].send_json({"type": "admitted"})
                        await g["ws"].send_json(make_sync_payload())
                        await g["ws"].send_json(make_queue_payload())
                        await g["ws"].send_json({"type": "chat_history", "messages": room.chat[-100:]})
                        await g["ws"].send_json({"type": "role_update", "role": g.get("role", "guest")})
                    await push_room_state_to_host()

            elif action == "reject":
                g = room.guests.get(msg.get("token"))
                if g:
                    if g["ws"]:
                        await g["ws"].send_json({"type": "rejected"})
                    room.guests.pop(msg["token"], None)
                    await push_room_state_to_host()

            elif action == "kick":
                tok = msg.get("token")
                g = room.guests.get(tok)
                if g:
                    if g["ws"]:
                        await g["ws"].send_json({"type": "kicked"})
                        try:
                            await g["ws"].close()
                        except Exception:
                            pass
                    # Mark banned in-memory (keep the entry so reconnect is caught)
                    g["ws"] = None
                    g["status"] = "banned"
                    # Persist to disk
                    _ban_list[tok] = {"name": g["name"], "bannedAt": time.time()}
                    save_ban_list(_ban_list)
                    await push_room_state_to_host()

            elif action == "promote_cohost":
                g = room.guests.get(msg.get("token"))
                if g and g["status"] == "admitted":
                    g["role"] = "cohost"
                    if g["ws"]:
                        await g["ws"].send_json({"type": "role_update", "role": "cohost"})
                    await push_room_state_to_host()

            elif action == "demote_cohost":
                g = room.guests.get(msg.get("token"))
                if g:
                    g["role"] = "guest"
                    if g["ws"]:
                        await g["ws"].send_json({"type": "role_update", "role": "guest"})
                    await push_room_state_to_host()

            elif action == "chat_send":
                entry = {"sender": "Host 👑", "text": msg.get("text", ""), "timestamp": time.time(), "role": "host"}
                room.chat.append(entry)
                await broadcast_to_all({"type": "chat_message", **entry})

            elif action == "chat_send_encrypted":
                # Forward encrypted payload without decrypting
                entry = {
                    "sender": "Host 👑",
                    "data": msg.get("data", ""),
                    "timestamp": time.time(),
                    "role": "host",
                    "encrypted": True
                }
                room.chat.append(entry)
                await broadcast_to_all({"type": "chat_message_encrypted", **entry})

            elif action == "approve_request":
                req = next((r for r in room.song_requests if r["id"] == msg.get("requestId")), None)
                if req:
                    room.song_requests.remove(req)
                    # Safety: for YouTube, always store the bare 11-char video ID,
                    # not a full URL (queue_next uses url directly as videoId).
                    url = req["url"]
                    if req["source"] == "youtube":
                        yt_match = re.search(r'(?:v=|/shorts/|/embed/|/live/|youtu\.be/)([\w-]{11})', url)
                        if yt_match:
                            url = yt_match.group(1)
                    room.queue.append({
                        "id": str(uuid.uuid4()), "source": req["source"],
                        "url": url, "title": req["title"], "addedBy": req["name"],
                    })
                    await broadcast_to_all(make_queue_payload())
                    await push_room_state_to_host()

            elif action == "dismiss_request":
                room.song_requests = [r for r in room.song_requests if r["id"] != msg.get("requestId")]
                await push_room_state_to_host()

            elif action in ("set_video", "set_spotify", "set_local", "play", "pause", "seek",
                            "queue_add", "queue_remove", "queue_reorder", "queue_next"):
                await handle_playback_action(action, msg)

    except WebSocketDisconnect:
        room.host_ws = None


# ---------------------------------------------------------------------------
# Guest WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws/guest")
async def ws_guest(websocket: WebSocket, token: str = Query(...), name: str = Query(...)):
    await websocket.accept()

    # Check persistent ban list first (covers server-restart scenario)
    if token in _ban_list:
        # Ensure in-memory entry is consistent
        if token not in room.guests:
            room.guests[token] = {
                "name": _ban_list[token].get("name", name or "Guest"),
                "ws": None,
                "status": "banned",
                "role": "guest",
            }
        await websocket.send_json({"type": "banned"})
        await websocket.close()
        return

    g = room.guests.get(token)
    if g and g["status"] == "banned":
        await websocket.send_json({"type": "banned"})
        await websocket.close()
        return

    if g:
        g["ws"] = websocket
        g["name"] = name or g["name"]
    else:
        room.guests[token] = {"name": name or "Guest", "ws": websocket, "status": "pending", "role": "guest"}
        g = room.guests[token]

    if g["status"] == "admitted":
        await websocket.send_json({"type": "admitted"})
        await websocket.send_json(make_sync_payload())
        await websocket.send_json(make_queue_payload())
        await websocket.send_json({"type": "chat_history", "messages": room.chat[-100:]})
        await websocket.send_json({"type": "role_update", "role": g.get("role", "guest")})
    else:
        await websocket.send_json({"type": "pending"})

    await push_room_state_to_host()

    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            action = msg.get("action")
            g = room.guests.get(token)
            if not g or g["status"] != "admitted":
                continue

            if action == "chat_send":
                entry = {
                    "sender": g["name"], "text": msg.get("text", ""),
                    "timestamp": time.time(), "role": g.get("role", "guest"),
                }
                room.chat.append(entry)
                await broadcast_to_all({"type": "chat_message", **entry})

            elif action == "chat_send_encrypted":
                entry = {
                    "sender": g["name"],
                    "data": msg.get("data", ""),
                    "timestamp": time.time(),
                    "role": g.get("role", "guest"),
                    "encrypted": True
                }
                room.chat.append(entry)
                await broadcast_to_all({"type": "chat_message_encrypted", **entry})

            elif action == "recommend":
                room.song_requests.append({
                    "id": str(uuid.uuid4()), "token": token,
                    "name": g["name"], "source": msg.get("source", "youtube"),
                    "url": msg.get("url", ""), "title": msg.get("title", "Unknown"),
                    "timestamp": time.time(),
                })
                await push_room_state_to_host()

            elif action in ("play", "pause", "seek", "set_video", "set_spotify", "set_local",
                            "queue_add", "queue_remove", "queue_reorder", "queue_next"):
                if g.get("role") == "cohost":
                    msg.setdefault("addedBy", g["name"])
                    await handle_playback_action(action, msg)

    except WebSocketDisconnect:
        g = room.guests.get(token)
        if g:
            g["ws"] = None
        await push_room_state_to_host()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# if __name__ == "__main__":
#     import uvicorn
#     ip = local_ip()
#     print("\n" + "=" * 60)
#     print("  LAN Listening Room v2")
#     print("=" * 60)
#     print(f"  yt-dlp: {'✓ available' if YT_DLP_AVAILABLE else '✗ not installed (pip install yt-dlp)'}")
#     print(f"  Guest link : http://{ip}:8000/join")
#     print(f"  Host panel : http://{ip}:8000/host?key={HOST_KEY}")
#     print("=" * 60 + "\n")
#     # uvicorn.run(app, host="0.0.0.0", port=8000)
#     uvicorn.run(app, host="0.0.0.0", port=8000, ssl_keyfile="key.pem", ssl_certfile="cert.pem")

if __name__ == "__main__":
    import uvicorn
    ip = local_ip()
    # Since you are using SSL, we force https in the printed links.
    # If you ever want to run without SSL, change this to "http".
    protocol = "https"
    print("\n" + "=" * 60)
    print("  LAN Listening Room v2")
    print("=" * 60)
    print(f"  yt-dlp: {'✓ available' if YT_DLP_AVAILABLE else '✗ not installed (pip install yt-dlp)'}")
    print(f"  Guest link : {protocol}://{ip}:8000/join")
    print(f"  Host panel : {protocol}://{ip}:8000/host?key={HOST_KEY}")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, ssl_keyfile="key.pem", ssl_certfile="cert.pem")