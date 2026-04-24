# ScrobbleBox v3

ScrobbleBox is a vinyl playback companion built around three coordinated services:

- `scrobblebox.core`: listens to audio input, identifies tracks, validates against Discogs, and scrobbles confirmed or inferred plays.
- `scrobblebox.lyrics`: drives a now-playing style display with album metadata, timing, and synchronized lyrics.
- `scrobblebox.oscilloscope`: powers an oscilloscope on when playback starts and off after extended silence.

## Project Layout

```text
src/scrobblebox/
  config.py
  core/
  lyrics/
  oscilloscope/
tests/
docs/
```

## Quick Start

1. Create a virtual environment.
2. Install the package in editable mode:

```powershell
python -m pip install -e .
```

3. Copy the example environment file and fill in your credentials:

```powershell
Copy-Item .env.example .env
```

4. Run a module entry point once implementation is in place:

```powershell
python -m scrobblebox.core.service
```

## Environment Variables

The real `.env` file is ignored by Git. Only `.env.example` should be committed to the public repository.

Current placeholders cover:

- Last.fm API credentials
- Discogs token and collection identifiers
- Shazam / audio capture configuration
- Lyrics server settings
- Kasa oscilloscope plug settings, including optional TP-Link credentials for newer devices

## Development Notes

- Python package layout uses `src/` to keep imports explicit.
- Runtime configuration is centralized in `scrobblebox.config`.
- Modules currently provide scaffolding and typed domain models so implementation can grow cleanly from the initial spec.

## Raspberry Pi

Deployment notes and `systemd` unit templates live in [`docs/raspberry-pi-setup.md`](docs/raspberry-pi-setup.md) and [`deploy/systemd/`](deploy/systemd/).

## TV Display

The lyrics service now exposes a TV-friendly now-playing page and JSON state endpoint:

- `http://<device>:8765/`
- `http://<device>:8765/api/now-playing`
