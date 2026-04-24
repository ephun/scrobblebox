from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scrobblebox.config import settings
from scrobblebox.lyrics.display import LyricRepository, build_view_model, parse_iso_utc
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
      --bg-1: #08111f;
      --bg-2: #102742;
      --bg-3: #173553;
      --panel: rgba(9, 19, 34, 0.84);
      --panel-soft: rgba(19, 34, 56, 0.9);
      --panel-border: rgba(255, 255, 255, 0.08);
      --text: #f7fafc;
      --muted: #b8c6d8;
      --accent: #79f2c0;
      --accent-2: #8ec5ff;
      --shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Aptos", "Segoe UI Variable Display", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(121, 242, 192, 0.16), transparent 30%),
        radial-gradient(circle at bottom right, rgba(142, 197, 255, 0.18), transparent 30%),
        linear-gradient(145deg, var(--bg-1), var(--bg-2) 52%, var(--bg-3));
      overflow: hidden;
    }
    .shell {
      display: grid;
      grid-template-columns: minmax(360px, 33vw) 1fr;
      min-height: 100vh;
      gap: 28px;
      padding: 28px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: 32px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(22px);
    }
    .info {
      padding: 28px;
      display: flex;
      flex-direction: column;
      gap: 22px;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 18px;
      border-radius: 999px;
      background: rgba(121, 242, 192, 0.12);
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.2em;
      font-size: 13px;
      font-weight: 700;
      width: fit-content;
    }
    .cover {
      width: 100%;
      aspect-ratio: 1 / 1;
      border-radius: 26px;
      object-fit: cover;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)),
        repeating-linear-gradient(45deg, rgba(255,255,255,0.03), rgba(255,255,255,0.03) 12px, transparent 12px, transparent 24px);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .eyebrow {
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 12px;
      font-weight: 700;
    }
    .title {
      font-size: clamp(46px, 5.6vw, 86px);
      line-height: 0.92;
      font-weight: 800;
      letter-spacing: -0.03em;
      text-wrap: balance;
    }
    .artist {
      color: var(--text);
      font-size: clamp(22px, 2.2vw, 34px);
      font-weight: 700;
      text-wrap: balance;
    }
    .meta {
      color: var(--muted);
      font-size: clamp(18px, 1.8vw, 26px);
      text-wrap: balance;
    }
    .bar {
      position: relative;
      height: 14px;
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
      font-size: 20px;
      font-weight: 600;
      letter-spacing: 0.04em;
    }
    .lyrics {
      padding: 28px;
      display: grid;
      grid-template-rows: 0.8fr 1.05fr 0.8fr;
      gap: 22px;
      min-height: 0;
    }
    .card {
      border-radius: 28px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.04);
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 28px 42px;
      font-size: clamp(28px, 3vw, 44px);
      line-height: 1.2;
      font-weight: 600;
      transition: transform 240ms ease, background 240ms ease, opacity 240ms ease, border-color 240ms ease;
    }
    .card.current {
      background: linear-gradient(135deg, rgba(121,242,192,0.16), rgba(142,197,255,0.14));
      border-color: rgba(121,242,192,0.36);
      transform: scale(1.015);
      font-size: clamp(38px, 4.2vw, 68px);
      font-weight: 800;
    }
    .message {
      color: var(--muted);
      background: rgba(255,255,255,0.03);
    }
    .statusline {
      display: flex;
      justify-content: space-between;
      color: var(--muted);
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
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
      <div class="eyebrow">Now Spinning</div>
      <div class="title" id="title">Listening...</div>
      <div class="artist" id="artist">ScrobbleBox</div>
      <div class="meta" id="album">Waiting for verified playback</div>
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
      const duration = s.display_duration_seconds || s.duration_seconds || 0;
      const percent = duration > 0 ? Math.min(100, (elapsed / duration) * 100) : 0;

      const chipLabel = s.audio_active ? (
        s.status === 'inferred' ? 'Inferred' :
        s.status === 'scrobbled' ? 'Confirmed' :
        'Now Playing'
      ) : 'Listening';
      els.chip.textContent = chipLabel;
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
      els.prev.textContent = s.previous_lyric || '';
      els.current.textContent = s.current_lyric || (playing ? 'No lyrics available.' : 'Listening...');
      els.next.textContent = s.next_lyric || '';
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


def track_index(state: dict) -> int | None:
    release_tracks = list(state.get("release_tracks") or [])
    position = state.get("position")
    if not position or not release_tracks:
        return None
    for index, item in enumerate(release_tracks):
        if item.get("position") == position:
            return index
    return None


def same_release_side(left: dict, right: dict) -> bool:
    return (
        bool(left.get("release_id"))
        and left.get("release_id") == right.get("release_id")
        and left.get("side") == right.get("side")
    )


def same_track(left: dict, right: dict) -> bool:
    return (
        same_release_side(left, right)
        and left.get("position") == right.get("position")
        and left.get("title") == right.get("title")
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def forward_only(previous: dict | None, current: dict) -> dict:
    if not previous or not previous.get("title"):
        return current
    if not current.get("title"):
        return current

    prev_index = track_index(previous)
    curr_index = track_index(current)
    if same_release_side(previous, current) and prev_index is not None and curr_index is not None:
        if curr_index < prev_index:
            return previous
        if curr_index == prev_index:
            prev_started = parse_iso_utc(previous.get("started_at"))
            curr_started = parse_iso_utc(current.get("started_at"))
            if prev_started and curr_started and curr_started > prev_started:
                current = dict(current)
                current["started_at"] = prev_started.isoformat()
                elapsed = max(0, int((utc_now() - prev_started).total_seconds()))
                current["elapsed_seconds"] = max(elapsed, int(previous.get("elapsed_seconds") or 0))
                if previous.get("previous_lyric"):
                    current["previous_lyric"] = previous["previous_lyric"]
                if previous.get("current_lyric") and current.get("current_lyric") in {"Listening...", "", "..."}:
                    current["current_lyric"] = previous["current_lyric"]
                if previous.get("next_lyric") and not current.get("next_lyric"):
                    current["next_lyric"] = previous["next_lyric"]
    return current


def build_handler(state_store: StateStore, repo: LyricRepository) -> type[BaseHTTPRequestHandler]:
    last_view: dict | None = None

    class LyricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            nonlocal last_view
            if self.path in {"/", "/index.html"}:
                self._send(HTTPStatus.OK, HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if self.path == "/api/now-playing":
                model = build_view_model(state_store.read(), repo)
                model = forward_only(last_view, model)
                last_view = model
                payload = json.dumps(model).encode("utf-8")
                self._send(HTTPStatus.OK, payload, "application/json; charset=utf-8")
                return
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")

        def do_HEAD(self) -> None:  # noqa: N802
            if self.path in {"/", "/index.html", "/api/now-playing"}:
                self.send_response(HTTPStatus.OK)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

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
        server = ThreadingHTTPServer(
            (self.host, self.port),
            build_handler(StateStore(), LyricRepository()),
        )
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
