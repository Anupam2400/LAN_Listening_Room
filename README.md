# LAN Listening Room

A small local-network app: you host a YouTube video, people on the same
wifi request to join, you admit/reject/kick them from a control panel,
and everyone's browser stays in sync with your play/pause/seek.

## How it works

- **You** run the server on your laptop/PC.
- **Guests** open `http://<your-ip>:8000/join`, type a name, and wait.
- **You** open `http://<your-ip>:8000/host?key=<your-key>` (printed when
  the server starts) — this is your private control panel. Don't share
  this link; share only the `/join` link.
- When someone requests to join, you'll see it live on the host panel
  with **Admit** / **Reject** buttons.
- Once admitted, their page loads the same video and stays synced to
  your play/pause/seek actions.
- You can **Kick** anyone, anytime, from the host panel.
- If a guest closes the tab and comes back later, they're remembered
  as a returning guest (by a private token stored in their browser),
  but they still have to be admitted again each time they reconnect.

## Setup

```bash
pip install -r requirements.txt
python main.py
```

The console will print two links:

```
Guest link (share with people you trust):
  http://192.168.1.23:8000/join

Host control panel (keep this private):
  http://192.168.1.23:8000/host?key=AbCdEf123...
```

Open the host link yourself, keep the join link for people you invite.
Both devices need to be on the same wifi network as the machine running
the server.

## Notes & limitations

- **This syncs playback, it doesn't relay your system audio.** Everyone's
  browser independently streams the same YouTube video; your play/pause/
  seek actions get broadcast and each guest's player jumps to match. This
  only works for videos that are public on YouTube (not local files or
  other apps' audio).
- **Anonymity is partial, not absolute.** Guests connect directly to your
  IP address, so your IP is visible to your router and, in principle, to
  anyone technically inclined among your guests. The app itself never
  shows your name — but on a local network, "who is the host" is not
  something that can be fully hidden from people you've directly given
  the link to. Since you're only sharing the `/join` link with people you
  already know, this is generally a non-issue.
- **The host key is your only access control** for the control panel —
  don't post it publicly, and restart the server (which generates a new
  key) if you think it's leaked.
- **State is in-memory.** Restarting the server clears all pending/
  admitted guests and resets "now playing." That's intentional for a
  personal-use tool — there's no database to manage.
- **Ports/firewall:** if guests can't connect, make sure your OS firewall
  allows inbound connections on port 8000 for your local network.

## Possible next steps

- Add a persistent ban list (a small JSON file) so once you reject/kick
  someone, reconnecting shows you "previously kicked" instead of a blank
  new request.
- Add a volume-per-guest or mute-all control.
- Swap synced YouTube playback for true audio relay (Icecast/WebRTC) if
  you want to share *anything* playing on your machine, not just YouTube.
