# Raspberry Pi Setup

This gets the current ScrobbleBox scaffold running as supervised services on a Raspberry Pi. At the moment the services stay alive and log their configured settings, but the audio recognition and UI features are not implemented yet.

## Assumptions

- Raspberry Pi OS Bookworm or newer
- A user named `pi`
- Git installed
- Python 3.11 available as `python3`
- You want the project installed at `/opt/scrobblebox`

## 1. Install system packages

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

If you plan to capture audio from a USB device later, also install:

```bash
sudo apt install -y portaudio19-dev alsa-utils
```

## 2. Clone the repository

```bash
sudo mkdir -p /opt/scrobblebox
sudo chown pi:pi /opt/scrobblebox
git clone https://github.com/ephun/scrobblebox.git /opt/scrobblebox
cd /opt/scrobblebox
```

## 3. Create the virtual environment

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

## 4. Configure environment variables

```bash
cp .env.example .env
nano .env
```

Populate the real credentials before enabling the services.

## 5. Test each service manually

Run each one in a separate terminal and stop it with `Ctrl+C`.

```bash
. .venv/bin/activate
python -m scrobblebox.core.service
python -m scrobblebox.lyrics.service
python -m scrobblebox.oscilloscope.service
```

## 6. Install the systemd units

```bash
sudo cp deploy/systemd/scrobblebox-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scrobblebox-core.service
sudo systemctl enable --now scrobblebox-lyrics.service
sudo systemctl enable --now scrobblebox-oscilloscope.service
```

## 7. Check service status

```bash
systemctl status scrobblebox-core.service
systemctl status scrobblebox-lyrics.service
systemctl status scrobblebox-oscilloscope.service
```

Follow logs with:

```bash
journalctl -u scrobblebox-core.service -f
journalctl -u scrobblebox-lyrics.service -f
journalctl -u scrobblebox-oscilloscope.service -f
```

## Updating on the Pi

```bash
cd /opt/scrobblebox
git pull
. .venv/bin/activate
pip install -r requirements.txt
pip install -e .
sudo systemctl restart scrobblebox-core.service
sudo systemctl restart scrobblebox-lyrics.service
sudo systemctl restart scrobblebox-oscilloscope.service
```

## Notes

- The current scaffold is safe to deploy, but it is not functionally complete.
- When audio capture and Shazam integration are added, more OS packages and device permissions will likely be needed.
- If your Pi user is not `pi`, update the `User=` lines in `deploy/systemd/*.service`.
