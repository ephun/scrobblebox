from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scrobblebox.config import settings
from scrobblebox.lyrics.state import StateStore


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

LOGGER = logging.getLogger(__name__)

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ScrobbleBox Lyrics</title>
  <style>
    :root {
      --bg-1: #0a1326;
      --bg-2: #13294b;
      --panel: rgba(7, 16, 31, 0.72);
      --panel-border: rgba(255, 255, 255, 0.08);
      --text: #f5f7fb;
      --muted: #9fb0c8;
      --accent: #ffd166;
      --accent-2: #64dfdf;
      --danger: #ef476f;
      --shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(255, 209, 102, 0.16), transparent 35%),
        radial-gradient(circle at bottom right, rgba(100, 223, 223, 0.15), transparent 30%),
        linear-gradient(135deg, var(--bg-1), var(--bg-2));
      overflow: hidden;
    }
    .shell {
      display: grid;
      grid-template-columns: minmax(320px, 34vw) 1fr;
      min-height: 100vh;
      gap: 24px;
      padding: 28px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: 28px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(22px);
    }
    .info {
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 16px;
      border-radius: 999px;
      background: rgba(255, 209, 102, 0.12);
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 12px;
      width: fit-content;
    }
    .cover {
      width: 100%;
      aspect-ratio: 1 / 1;
      border-radius: 24px;
      object-fit: cover;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)),
        repeating-linear-gradient(45deg, rgba(255,255,255,0.03), rgba(255,255,255,0.03) 12px, transparent 12px, transparent 24px);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .marquee {
      overflow: hidden;
      white-space: nowrap;
      position: relative;
    }
    .marquee > span {
      display: inline-block;
      padding-right: 2rem;
      min-width: 100%;
      animation: marquee 14s linear infinite;
    }
    .title { font-size: clamp(36px, 4vw, 64px); line-height: 0.95; font-weight: 700; }
    .meta { color: var(--muted); font-size: clamp(18px, 1.8vw, 26px); }
    .bar {
      position: relative;
      height: 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.08);
      overflow: hidden;
    }
    .bar > div {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      transition: width 0.6s linear;
    }
    .times {
      display: flex;
      justify-content: space-between;
      color: var(--muted);
      font-size: 18px;
      letter-spacing: 0.04em;
    }
    .lyrics {
      padding: 28px;
      display: grid;
      grid-template-rows: 1fr 1fr 1fr;
      gap: 18px;
      min-height: 0;
    }
    .card {
      border-radius: 24px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.04);
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 24px;
      font-size: clamp(22px, 2.5vw, 40px);
      line-height: 1.15;
    }
    .card.current {
      background: linear-gradient(135deg, rgba(255,209,102,0.16), rgba(100,223,223,0.12));
      border-color: rgba(255,209,102,0.28);
      transform: scale(1.015);
    }
    .message { color: var(--muted); }
    .statusline {
      display: flex;
      justify-content: space-between;
      color: var(--muted);
      font-size: 14px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    @keyframes marquee {
      0%, 12% { transform: translateX(0); }
      88%, 100% { transform: translateX(-100%); }
    }
    @media (max-width: 900px) {
      .shell { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
      body { overflow: auto; }
      .lyrics { min-height: 55vh; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="panel info">
      <div class="chip" id="chip">Listening</div>
      <img class="cover" id="cover" alt="Album art">
      <div class="marquee title"><span id="title">Listening...</span></div>
      <div class="marquee meta"><span id="artist">ScrobbleBox</span></div>
      <div class="marquee meta"><span id="album">Waiting for verified playback</span></div>
      <div class="bar"><div id="progress"></div></div>
      <div class="times">
        <span id="elapsed">0:00</span>
        <span id="duration">0:00</span>
      </div>
      <div class="statusline">
        <span id="position">No side</span>
        <span id="updated">No signal</span>
      </div>
    </section>
    <section class="panel lyrics">
      <div class="card message" id="prev">Listening...</div>
      <div class="card current" id="current">No lyrics available.</div>
      <div class="card message" id="next">Waiting for lyric sync.</div>
    </section>
  </div>
  <script>
    const els = {
      chip: document.getElementById('chip'),
      cover: document.getElementById('cover'),
      title: document.getElementById('title'),
      artist: document.getElementById('artist'),
      album: document.getElementById('album'),
      progress: document.getElementById('progress'),
      elapsed: document.getElementById('elapsed'),
      duration: document.getElementById('duration'),
      position: document.getElementById('position'),
      updated: document.getElementById('updated'),
      prev: document.getElementById('prev'),
      current: document.getElementById('current'),
      next: document.getElementById('next'),
    };
    let state = null;

    function fmt(totalSeconds) {
      if (!totalSeconds || totalSeconds < 0) return '0:00';
      const mins = Math.floor(totalSeconds / 60);
      const secs = Math.floor(totalSeconds % 60).toString().padStart(2, '0');
      return `${mins}:${secs}`;
    }

    function elapsedSeconds(startedAt) {
      if (!startedAt) return 0;
      return Math.max(0, Math.floor((Date.now() - Date.parse(startedAt)) / 1000));
    }

    function render() {
      const s = state || {status: 'listening', message: 'Listening...', audio_active: false};
      const playing = !!s.title;
      const elapsed = playing ? elapsedSeconds(s.started_at) : 0;
      const duration = s.duration_seconds || 0;
      const percent = duration > 0 ? Math.min(100, (elapsed / duration) * 100) : 0;

      els.chip.textContent = s.audio_active ? (s.status === 'scrobbled' ? 'Confirmed' : 'Now Playing') : 'Listening';
      els.title.textContent = playing ? s.title : (s.message || 'Listening...');
      els.artist.textContent = playing ? s.artist : 'ScrobbleBox';
      els.album.textContent = playing ? (s.album || 'Unknown album') : 'Waiting for verified playback';
      els.cover.src = s.artwork_url || '';
      els.cover.style.visibility = s.artwork_url ? 'visible' : 'hidden';
      els.progress.style.width = `${percent}%`;
      els.elapsed.textContent = fmt(elapsed);
      els.duration.textContent = duration ? fmt(duration) : '0:00';
      els.position.textContent = s.position ? `${s.position}${s.side ? ' • Side ' + s.side : ''}` : 'No side';
      els.updated.textContent = s.updated_at ? new Date(s.updated_at).toLocaleTimeString() : 'No signal';
      els.prev.textContent = playing ? 'Previous lyric unavailable.' : 'Listening...';
      els.current.textContent = playing ? 'No lyrics available.' : 'Listening...';
      els.next.textContent = playing ? 'Lyric sync not implemented yet.' : 'Waiting for lyric sync.';
    }

    async function refresh() {
      try {
        const res = await fetch('/api/now-playing', {cache: 'no-store'});
        state = await res.json();
        render();
      } catch {
        state = null;
        render();
      }
    }

    refresh();
    render();
    setInterval(refresh, 2000);
    setInterval(render, 1000);
  </script>
</body>
</html>
"""


def build_handler(state_store: StateStore) -> type[BaseHTTPRequestHandler]:
    class LyricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/", "/index.html"}:
                self._send(HTTPStatus.OK, HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if self.path == "/api/now-playing":
                payload = json.dumps(state_store.read()).encode("utf-8")
                self._send(HTTPStatus.OK, payload, "application/json; charset=utf-8")
                return
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")

        def log_message(self, fmt: str, *args) -> None:
            LOGGER.info("lyrics http: " + fmt, *args)

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return LyricsHandler


@dataclass(slots=True)
class LyricsService:
    """Serve a TV-friendly now-playing display."""

    host: str = settings.lyrics_host
    port: int = settings.lyrics_port

    def run(self) -> None:
        LOGGER.info("Starting ScrobbleBox Lyrics on %s:%s", self.host, self.port)
        server = ThreadingHTTPServer((self.host, self.port), build_handler(StateStore()))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("ScrobbleBox Lyrics stopped.")
        finally:
            server.server_close()


def main() -> None:
    LyricsService().run()


if __name__ == "__main__":
    main()
