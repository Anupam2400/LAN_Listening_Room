<div align="center">

# 🎵 LAN Listening Room

**A self-hosted, real-time synchronized music room for your local network.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![WebSocket](https://img.shields.io/badge/WebSocket-Real--Time-4A90D9?style=flat-square)](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Release](https://img.shields.io/badge/Release-v1.0.0-brightgreen?style=flat-square)](https://github.com/Anupam2400/LAN_Listening_Room/releases/tag/v1.0.0)

Host a private synchronized music session on your LAN. Play YouTube, Spotify embeds, or local audio — all guests hear the same thing, in sync, in real time.

</div>

---

## ✨ Features

| Feature | Description |
|---|---|
| 🎬 **Multi-Source Playback** | YouTube, Spotify embeds, and local audio file uploads (MP3, WAV, OGG, FLAC, AAC, OPUS, WebM) |
| 🔄 **Real-Time Sync** | Play, pause, seek — all guests instantly jump to the same position via WebSocket |
| 🎛️ **Host Control Panel** | Private, key-protected dashboard to manage the entire room |
| 👥 **Guest Access Control** | Admit / Reject / Kick guests with live status updates |
| 👑 **Co-Host System** | Promote trusted guests to co-host so they can control playback alongside you |
| 📋 **Song Queue** | Drag-to-reorder queue with multi-source support |
| 🎤 **Song Recommendations** | Guests can suggest songs; host approves or dismisses each request |
| 💬 **Real-Time Chat** | Full chat room with role badges (Host 👑, Co-Host, Guest) |
| 🔐 **Encrypted Chat** | Optional end-to-end encrypted messages for private conversations |
| 🔒 **HTTPS / WSS** | SSL/TLS support out of the box (self-signed cert included for LAN use) |
| 🤖 **yt-dlp Fallback** | Age-restricted or embed-blocked YouTube videos are streamed via `yt-dlp` |
| 🔑 **Ephemeral Security** | One-time host key generated fresh on every server start |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      LAN Listening Room                      │
│                                                              │
│   FastAPI + Uvicorn (Python)                                 │
│   ┌─────────────┐   ┌─────────────┐   ┌──────────────────┐  │
│   │  /ws/host   │   │  /ws/guest  │   │  HTTP REST API   │  │
│   │  WebSocket  │   │  WebSocket  │   │  /api/upload     │  │
│   └──────┬──────┘   └──────┬──────┘   │  /api/yt-audio   │  │
│          │                 │           └──────────────────┘  │
│          └────────┬────────┘                                 │
│                   │  In-memory Room State                    │
│              ┌────▼────┐                                     │
│              │  Room   │  now_playing · queue · chat         │
│              │  State  │  guests · song_requests             │
│              └─────────┘                                     │
└──────────────────────────────────────────────────────────────┘

Browser Clients
  host.html  →  WebSocket /ws/host  (key-protected)
  guest.html →  WebSocket /ws/guest (token-based)
```

**Tech stack:**
- **Backend:** Python 3.10+, [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), `yt-dlp` (optional)
- **Frontend:** Vanilla HTML / CSS / JavaScript (no build step, no npm)
- **Transport:** WebSockets for all real-time events; plain HTTP for file uploads and stream URL resolution

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/Anupam2400/LAN_Listening_Room.git
cd LAN_Listening_Room
```

### 2. Create a virtual environment & install dependencies

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. SSL Certificates (for HTTPS/WSS)

The repo ships **without** certificates (they are gitignored for security).  
Generate a self-signed cert for LAN use:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem \
  -days 365 -nodes -subj "/CN=localhost"
```

> **Skip SSL?** Edit the last line of `main.py` — remove the `ssl_keyfile` and `ssl_certfile` arguments to run in plain HTTP mode on `http://<your-ip>:8000`.

### 4. Run the server

```bash
python main.py
```

The console prints two links:

```
============================================================
  LAN Listening Room v2
============================================================
  yt-dlp: ✓ available
  Guest link : https://192.168.1.42:8000/join
  Host panel : https://192.168.1.42:8000/host?key=AbCdEf123...
============================================================
```

- **Share the guest link** with people on your LAN/Wi-Fi.
- **Keep the host link private** — it's your control panel.

---

## 🖥️ Usage

### For the Host

1. Open the **Host Panel** URL printed in the console.
2. Browsers will warn about the self-signed certificate — click **"Advanced → Proceed"**.
3. Paste a YouTube URL / Spotify link, or upload a local audio file.
4. When guests request to join, **Admit** or **Reject** them from the panel.
5. Promote trusted guests to **Co-Host** so they can share playback control.

### For Guests

1. Open the **Guest Link** in a browser on the same network.
2. Type your display name and click **Join**.
3. Wait for the host to admit you — the room syncs automatically.
4. Use the **Recommend** button to suggest songs to the host.

---

## 📡 WebSocket Protocol

All real-time communication uses JSON messages over WebSocket.

### Host → Server (selected actions)

| Action | Payload fields | Effect |
|---|---|---|
| `set_video` | `videoId`, `title` | Play a YouTube video |
| `set_spotify` | `spotifyUri`, `title` | Load a Spotify embed |
| `set_local` | `fileUrl`, `title` | Play an uploaded file |
| `play` / `pause` | `position` | Sync playback state |
| `seek` | `position` | Seek all clients |
| `queue_add` | `source`, `url`, `title` | Add to queue |
| `queue_next` | — | Pop and play next |
| `admit` / `reject` / `kick` | `token` | Manage guest access |
| `promote_cohost` / `demote_cohost` | `token` | Manage roles |
| `approve_request` / `dismiss_request` | `requestId` | Handle recommendations |
| `chat_send` | `text` | Broadcast chat message |
| `chat_send_encrypted` | `data` | Broadcast encrypted message |

### Server → Clients (selected events)

| Event type | Description |
|---|---|
| `sync` | Full playback state (source, position, isPlaying) |
| `queue_update` | Full queue array |
| `room_state` | Guest list + song requests |
| `chat_message` | New chat message |
| `admitted` / `rejected` / `kicked` / `banned` | Guest status change |
| `role_update` | Guest role changed (guest ↔ co-host) |

---

## 📁 Project Structure

```
LAN_Listening_Room/
├── main.py              # FastAPI app — all backend logic
├── requirements.txt     # Python dependencies
├── uploads/             # Runtime upload directory (gitignored)
├── static/
│   ├── host.html        # Host control panel (SPA)
│   └── guest.html       # Guest room view (SPA)
└── README.md
```

---

## 🔐 Security Notes

- **Host key is ephemeral:** A new cryptographically random key is generated every time the server starts via `secrets.token_urlsafe(9)`.
- **SSL/TLS:** Run with `ssl_keyfile` / `ssl_certfile` to encrypt all traffic (recommended, even on LAN).
- **Never commit** `key.pem` / `cert.pem` — they are gitignored.
- **Uploaded files** are stored in `uploads/` with a UUID filename to prevent path traversal. Only audio MIME types are accepted.
- **Guest tokens** are UUIDs stored in `localStorage`; reconnecting guests must still be re-admitted.

---

## 🛣️ Roadmap

- [ ] Persistent ban list (JSON file) so kicked guests are flagged on reconnect
- [ ] Per-guest volume / mute control
- [ ] Room history / playback log
- [ ] WebRTC audio relay (stream *anything* playing on the host machine, not just YouTube)
- [ ] Multiple concurrent rooms
- [ ] Docker / `docker-compose` deployment for easier setup
- [ ] React/Vue frontend rewrite for better maintainability

---

## 🤝 Contributing

Contributions, bug reports, and feature requests are welcome!

1. **Fork** the repo and create a branch: `git checkout -b feature/your-feature`
2. Make your changes and commit with a descriptive message
3. Open a **Pull Request** against the `develop` branch

Please open an issue first for significant changes.

---

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

---

<div align="center">

Made with ❤️ by [Anupam2400](https://github.com/Anupam2400) · Built for GSoC 2027 preparation

</div>
