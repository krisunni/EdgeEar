# ravenSDR — Deployment Runbook

## Target Environment
- Raspberry Pi 5 running Raspberry Pi OS (Bookworm, 64-bit)
- Hailo AI Hat (Hailo-8L, 13 TOPS)
- RTL-SDR Blog V4 (R828D tuner)

## Deployment Steps

1. Clone repository to Pi
2. Run `code/setup.sh` to install system dependencies
3. Create venv: `python3 -m venv venv && source venv/bin/activate`
4. Install Python deps: `pip install -r code/requirements.txt`
5. Verify SDR: `rtl_test -t`
6. Verify Hailo: `hailortcli fw-control identify`
7. Start app: `python3 code/ravensdr/app.py`
8. Open http://localhost:5000

## Development (No Hardware)

1. Install Python deps (skip setup.sh)
2. Run `python3 code/ravensdr/app.py`
3. App auto-detects no SDR, starts in Web Stream mode
4. Select NOAA Monterey preset for testing
