# LAN Listening Room — Major Feature Expansion

## Overview

The current app supports YouTube-only playback with a single fixed host. We're expanding it significantly with the following new features:

1. **Multi-source playback** — Spotify embeds + local/downloaded files, alongside YouTube
2. **Bypass for restricted YouTube videos** — yt-dlp audio extraction fallback
3. **Song Queue** — Auto-advancing playlist managed by the host
4. **Chat + Song Recommendations** — Guests can chat and suggest songs to the host
5. **Co-host system** — Host can promote guests to co-host; co-hosts can control playback; original host (super-host) can demote any co-host

---

## User Review Required

> [!IMPORTANT]
> **Spotify embeds are read-only**: The official Spotify Embed SDK allows embedding a playback widget, but **Spotify does NOT allow programmatic play/pause/seek from a third-party page** unless the viewer is logged in to Spotify in their own browser. All guests must be Spotify-authenticated to hear audio — there's no way around this (it's a Spotify policy, not a bug). The embed approach is **best used for previewing/showing what's playing** while the audio syncs naturally through Spotify on each user's device.
> 
> **Alternative**: Use Spotify share links so the host picks a track, the track info is broadcast, and users who want audio open it in their own Spotify app. I'll implement the embed + visual sync approach which is the best achievable.

> [!IMPORTANT]
> **yt-dlp fallback for restricted YouTube videos**: When a YouTube video has embedding disabled (error 101/150), we can use `yt-dlp` on the server to extract the direct audio stream URL and serve it via an HTML5 `<audio>` element. This works for most videos but requires `yt-dlp` to be installed on the server machine. I'll add this as an optional server-side feature with graceful fallback.

> [!WARNING]
> **Local file hosting**: Uploaded/local audio files will be served from a temporary uploads directory on the LAN server. Files are stored in memory/disk during the session. There's no persistence across server restarts.

---

## Open Questions

> [!NOTE]
> 1. For the **co-host** feature: Should co-hosts be able to add/kick other guests? Or only control playback and queue? *(I'll implement: co-hosts can control playback + queue, but only the super-host can admit/kick guests and promote/demote co-hosts)*
> 2. For **local file uploads**: Should I allow any audio format (mp3, flac, ogg, wav) or only mp3? *(I'll support all common formats)*
> 3. For **song recommendations from guests**: Should these go into a separate "Requests" panel on the host side, or directly into the queue? *(I'll put them in a separate "Requests" panel so the host/co-host can approve)*

---

## Proposed Changes

### Backend (`main.py`)

Major rewrite of the room state and WebSocket message handlers.

#### [MODIFY] [main.py](file:///home/administrator/Videos/personal/LAN_Listening_Room/main.py)

- **Room state** — add `queue: list`, `chat: list`, `co_hosts: set[token]`, `super_host_key`
- **`/ws/host`** — handle new actions: `queue_add`, `queue_remove`, `queue_reorder`, `next_track`, `promote_cohost`, `demote_cohost`, `chat_send`
- **`/ws/guest`** — now receives messages (chat, recommend song); co-hosts get expanded permissions
- **New endpoint `/ws/cohost`** — co-host WebSocket that has playback + queue controls but not admin controls (OR handle via token-based role in a unified guest WS)
- **New endpoint `/upload`** — multipart file upload for local audio; saves to `uploads/` dir; returns a served URL
- **New endpoint `/yt-audio`** — calls `yt-dlp` to get direct stream URL for restricted videos (server-side only)
- **`/uploads` static mount** — serve uploaded audio files

---

### Host UI (`static/host.html`)

Complete redesign with a multi-panel tabbed layout.

#### [MODIFY] [static/host.html](file:///home/administrator/Videos/personal/LAN_Listening_Room/static/host.html)

**New layout: 3-column**
- **Left**: Player area (YouTube iframe / Spotify embed / HTML5 audio), source tabs (YouTube | Spotify | Local File), transport controls
- **Center**: Queue panel (drag-to-reorder list, now-playing indicator, skip button), Song Requests from guests
- **Right**: Guests panel (pending/admitted/co-hosts), Chat panel

**New UI features:**
- Source selector tabs (YouTube / Spotify / Upload)
- Queue list with drag-to-reorder, remove, and "play now" buttons
- Song request cards from guests (Approve → adds to queue, Dismiss)
- Chat window (host can read + send messages)
- Guest cards now show "Make Co-Host" / "Remove Co-Host" buttons for admitted guests
- Co-host badge on guest cards

---

### Guest UI (`static/guest.html`)

Expanded from a simple viewer to an active participant UI.

#### [MODIFY] [static/guest.html](file:///home/administrator/Videos/personal/LAN_Listening_Room/static/guest.html)

**New layout after admission:**
- Player (synced as before, now also supports Spotify embed / HTML5 audio)
- **"Now Playing" bar** with track title, source icon
- **Queue display** — read-only list of upcoming songs
- **Chat panel** — guests can send/receive messages
- **"Recommend a Song" button** — paste YouTube/Spotify URL or search; sends recommendation to host

**Co-host UI (when promoted):**
- Unlocks playback controls (play/pause, skip, seek)
- Can add songs to queue
- "CO-HOST" badge shown in header

---

### New Files

#### [NEW] `static/uploads/` directory
- Placeholder directory for uploaded audio files

#### [NEW] `requirements.txt` update
- Add `yt-dlp` as optional dependency (with try/except in code)
- Add `python-multipart` for file upload support

---

## Architecture: WebSocket Message Protocol

### New message types (server → client):
| Type | Payload | Recipients |
|------|---------|------------|
| `queue_update` | `{queue: [{id, title, source, url}]}` | all |
| `chat_message` | `{sender, text, timestamp}` | all |
| `song_request` | `{from, name, url, title}` | host only |
| `room_state` | (extended) + `co_hosts: [token]` | host |
| `role_update` | `{role: "cohost"\|"guest"}` | specific guest |
| `now_playing` | `{source, title, url, videoId}` | all |

### New message types (client → server):
| Action | From | Payload |
|--------|------|---------|
| `queue_add` | host/cohost | `{source, url, title}` |
| `queue_remove` | host/cohost | `{index}` |
| `queue_reorder` | host/cohost | `{from, to}` |
| `queue_next` | host/cohost | `{}` |
| `chat_send` | any admitted | `{text}` |
| `recommend` | any admitted | `{url, title, source}` |
| `promote_cohost` | host only | `{token}` |
| `demote_cohost` | host only | `{token}` |

---

## Verification Plan

### Automated Tests
- Start the server: `cd /home/administrator/Videos/personal/LAN_Listening_Room && python main.py`
- Open host panel in browser subagent, verify all tabs and panels load
- Open guest page, join, verify chat and recommend UI appear after admission

### Manual Verification
- Test YouTube load (normal + restricted video yt-dlp fallback)
- Test Spotify embed display
- Test local file upload and playback
- Test queue: add songs, auto-advance, reorder
- Test chat between host and guest
- Test co-host promotion: guest gets controls, can add to queue
- Test co-host demotion: controls disappear
- Test super-host override always works
