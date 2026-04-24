from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scrobblebox.config import settings
from scrobblebox.lyrics.display import LastfmRepository, LyricRepository, build_view_model, parse_iso_utc
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
      --bg-1: #050807;
      --bg-2: #0b1210;
      --bg-3: #111917;
      --glow: rgba(30, 215, 96, 0.18);
      --panel: rgba(10, 14, 12, 0.9);
      --panel-border: rgba(255, 255, 255, 0.06);
      --text: #f6f8f6;
      --muted: #b6c0ba;
      --accent: #1ed760;
      --accent-2: #9af0b7;
      --shadow: 0 28px 90px rgba(0, 0, 0, 0.52);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Avenir Next", "Montserrat", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, var(--glow), transparent 28%),
        radial-gradient(circle at bottom right, rgba(154, 240, 183, 0.08), transparent 32%),
        linear-gradient(148deg, var(--bg-1), var(--bg-2) 48%, var(--bg-3));
      overflow: hidden;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background:
        linear-gradient(160deg, rgba(255,255,255,0.02), transparent 26%),
        linear-gradient(0deg, rgba(0,0,0,0.28), rgba(0,0,0,0.28));
      pointer-events: none;
    }
    .shell {
      display: grid;
      grid-template-columns: minmax(420px, 35vw) 1fr;
      min-height: 100vh;
      gap: 34px;
      padding: 34px;
    }
    .panel {
      position: relative;
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: 34px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(26px);
    }
    .info {
      padding: 34px;
      display: flex;
      flex-direction: column;
      gap: 28px;
    }
    .chip-row {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      padding: 26px 42px;
      border-radius: 999px;
      background: rgba(30, 215, 96, 0.14);
      color: var(--accent);
      text-transform: uppercase;
      font-variant-caps: all-small-caps;
      letter-spacing: 0.1em;
      font-size: 44px;
      font-weight: 760;
      width: fit-content;
    }
    .chip.alt {
      background: rgba(140, 24, 36, 0.24);
      border: 1px solid rgba(255, 78, 108, 0.3);
      color: #ff637d;
    }
    .cover {
      width: 100%;
      aspect-ratio: 1 / 1;
      border-radius: 28px;
      object-fit: cover;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)),
        repeating-linear-gradient(45deg, rgba(255,255,255,0.03), rgba(255,255,255,0.03) 12px, transparent 12px, transparent 24px);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .title {
      font-size: clamp(82px, 7.4vw, 128px);
      line-height: 1.08;
      font-weight: 800;
      letter-spacing: -0.035em;
      text-shadow: 0 8px 24px rgba(0,0,0,0.32);
      padding-bottom: 0.02em;
    }
    .title .ticker-track {
      padding-bottom: 0;
    }
    .artist {
      color: var(--text);
      font-size: clamp(46px, 3.5vw, 62px);
      font-weight: 750;
    }
    .meta {
      color: var(--muted);
      font-size: clamp(36px, 2.9vw, 48px);
      font-weight: 600;
    }
    .ticker {
      overflow: hidden;
      position: relative;
      white-space: nowrap;
    }
    .ticker-track {
      display: inline-flex;
      align-items: baseline;
      gap: 3.5rem;
      min-width: max-content;
      transform: translate3d(0, 0, 0);
    }
    .ticker-copy {
      display: none;
    }
    .ticker.overflow .ticker-copy {
      display: inline;
    }
    .ticker.overflow .ticker-track {
      animation: marquee var(--ticker-duration, 16s) linear infinite;
    }
    @keyframes marquee {
      0%, 16% { transform: translateX(0); }
      84%, 100% { transform: translateX(calc(-1 * var(--ticker-distance, 0px))); }
    }
    .bar {
      position: relative;
      height: 20px;
      border-radius: 999px;
      background: rgba(255,255,255,0.08);
      overflow: hidden;
    }
    .bar > div {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      box-shadow: 0 0 18px rgba(30,215,96,0.45);
    }
    .times {
      display: flex;
      justify-content: space-between;
      color: var(--muted);
      font-size: 34px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }
    .lyrics {
      padding: 34px;
      display: grid;
      grid-template-rows: 0.8fr 1.05fr 0.8fr;
      gap: 26px;
      min-height: 0;
      background: linear-gradient(180deg, rgba(255,255,255,0.015), rgba(255,255,255,0.03));
    }
    .card {
      border-radius: 28px;
      border: 1px solid rgba(255,255,255,0.06);
      background: rgba(255,255,255,0.035);
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 34px 48px;
      font-size: clamp(60px, 4.4vw, 88px);
      line-height: 1.14;
      font-weight: 650;
      overflow-wrap: anywhere;
      word-break: normal;
      overflow: hidden;
    }
    .card.current {
      background: linear-gradient(135deg, rgba(30,215,96,0.18), rgba(154,240,183,0.1));
      border-color: rgba(30,215,96,0.36);
      font-weight: 800;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
    }
    .message {
      color: var(--muted);
      background: rgba(255,255,255,0.03);
    }
    .statusline {
      display: flex;
      justify-content: space-between;
      color: var(--muted);
      font-size: 30px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      gap: 18px;
    }
    @media (max-width: 900px) {
      .shell { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
      body { overflow: auto; }
      .lyrics { min-height: 55vh; }
      .title { font-size: clamp(58px, 10vw, 88px); }
      .artist { font-size: clamp(34px, 6vw, 48px); }
      .meta { font-size: clamp(28px, 4.5vw, 40px); }
      .card { font-size: clamp(40px, 5.8vw, 58px); }
      .times, .statusline, .chip { font-size: 32px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="panel info">
      <img class="cover" id="cover" alt="Album art">
      <div class="chip-row">
        <div class="chip" id="chip">Listening</div>
        <div class="chip alt" id="lastfm-chip">Last.fm --</div>
      </div>
      <div class="title ticker" id="title"><span class="ticker-track"><span class="ticker-primary">Listening...</span><span class="ticker-copy">Listening...</span></span></div>
      <div class="artist ticker" id="artist"><span class="ticker-track"><span class="ticker-primary">ScrobbleBox</span><span class="ticker-copy">ScrobbleBox</span></span></div>
      <div class="meta ticker" id="album"><span class="ticker-track"><span class="ticker-primary">Waiting for verified playback</span><span class="ticker-copy">Waiting for verified playback</span></span></div>
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
      lastfmChip: document.getElementById('lastfm-chip'),
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
    let renderedLyrics = { prev: '', current: '', next: '' };
    let renderedMeta = { title: '', artist: '', album: '' };

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

    function setTicker(el, text) {
      const track = document.createElement('span');
      track.className = 'ticker-track';
      const primary = document.createElement('span');
      primary.className = 'ticker-primary';
      primary.textContent = text;
      const copy = document.createElement('span');
      copy.className = 'ticker-copy';
      copy.textContent = text;
      track.replaceChildren(primary, copy);
      el.replaceChildren(track);
      el.classList.remove('overflow');
      el.style.removeProperty('--ticker-distance');
      el.style.removeProperty('--ticker-duration');
    }

    function updateTickers() {
      [els.title, els.artist, els.album].forEach((el) => {
        el.classList.remove('overflow');
        const primary = el.querySelector('.ticker-primary');
        if (!primary) return;
        const overflow = primary.scrollWidth - el.clientWidth;
        if (overflow > 8) {
          const distance = overflow + 56;
          const duration = Math.max(10, Math.min(24, distance / 22));
          el.style.setProperty('--ticker-distance', `${distance}px`);
          el.style.setProperty('--ticker-duration', `${duration}s`);
          el.classList.add('overflow');
        }
      });
    }

    function animateLyrics(prevText, currentText, nextText) {
      const changed = (
        renderedLyrics.prev !== prevText ||
        renderedLyrics.current !== currentText ||
        renderedLyrics.next !== nextText
      );
      els.prev.textContent = prevText;
      els.current.textContent = currentText;
      els.next.textContent = nextText;
      if (!changed) return;
      [els.prev, els.current, els.next].forEach((el) => {
        el.classList.remove('animate');
        void el.offsetWidth;
        el.classList.add('animate');
      });
      renderedLyrics = { prev: prevText, current: currentText, next: nextText };
    }

    function render() {
      const s = state || {status: 'listening', message: 'Listening...', audio_active: false};
      const playing = !!s.title;
      const elapsed = playing ? elapsedSeconds(s.started_at) : 0;
      const duration = s.display_duration_seconds || s.duration_seconds || 0;
      const percent = duration > 0 ? Math.min(100, (elapsed / duration) * 100) : 0;
      const titleText = playing ? s.title : (s.message || 'Listening...');
      const artistText = playing ? s.artist : 'ScrobbleBox';
      const albumText = playing ? (s.album || 'Unknown album') : 'Waiting for verified playback';

      const chipLabel = s.audio_active ? 'Now Playing' : 'Listening';
      els.chip.textContent = chipLabel;
      if (typeof s.lastfm_playcount === 'number') {
        els.lastfmChip.textContent = s.lastfm_playcount === 1 ? 'Last.fm 1 play' : `Last.fm ${s.lastfm_playcount} plays`;
        els.lastfmChip.style.display = 'inline-flex';
      } else {
        els.lastfmChip.textContent = 'Last.fm --';
        els.lastfmChip.style.display = playing ? 'inline-flex' : 'none';
      }
      if (renderedMeta.title !== titleText) {
        setTicker(els.title, titleText);
        renderedMeta.title = titleText;
      }
      if (renderedMeta.artist !== artistText) {
        setTicker(els.artist, artistText);
        renderedMeta.artist = artistText;
      }
      if (renderedMeta.album !== albumText) {
        setTicker(els.album, albumText);
        renderedMeta.album = albumText;
      }
      els.cover.src = s.artwork_url || '';
      els.cover.style.visibility = s.artwork_url ? 'visible' : 'hidden';
      els.progress.style.width = `${percent}%`;
      els.elapsed.textContent = fmt(elapsed);
      els.duration.textContent = duration ? fmt(duration) : '0:00';
      els.position.textContent = s.position ? `${s.position}${s.side ? ' | Side ' + s.side : ''}` : 'No side';
      els.updated.textContent = s.updated_at ? new Date(s.updated_at).toLocaleTimeString() : 'No signal';
      animateLyrics(
        s.previous_lyric || '',
        s.current_lyric || (playing ? 'No lyrics available.' : 'Listening...'),
        s.next_lyric || '',
      );
      requestAnimationFrame(updateTickers);
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
    setInterval(refresh, 500);
    setInterval(render, 250);
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
    return current


def build_handler(state_store: StateStore, repo: LyricRepository, lastfm: LastfmRepository) -> type[BaseHTTPRequestHandler]:
    last_view: dict | None = None

    class LyricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            nonlocal last_view
            if self.path in {"/", "/index.html"}:
                self._send(HTTPStatus.OK, HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if self.path == "/api/now-playing":
                model = build_view_model(state_store.read(), repo, lastfm)
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
            build_handler(StateStore(), LyricRepository(), LastfmRepository()),
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
