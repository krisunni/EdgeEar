# Phase 9 — Setup Script & Requirements

## Objective
Create the one-shot installer script and Python requirements file for deployment on Raspberry Pi.

## Scope
- `setup.sh` — 9-step system installer
- `requirements.txt` — Python pip dependencies
- V4-specific packages (rtl-biast)

---

## Sub-Phase 9.1 — Setup Script

### Tasks

| ID | Task | Status |
|---|---|---|
| T025 | Create setup.sh installer script | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/setup.sh` | One-shot system dependency installer |

### Script Steps
1. Check running on Raspberry Pi OS (warn if not)
2. `apt install` all system packages (rtl-sdr, librtlsdr-dev, rtl-biast, sox, alsa-utils, ffmpeg)
3. `modprobe snd-aloop` + persist in `/etc/modules`
4. Blacklist `dvb_usb_rtl28xxu` kernel module
5. Create Python venv and install pip packages
6. Test SDR with `rtl_test -t` — confirm R828D tuner
7. Verify bias tee is off: `rtl_biast -b 0`
8. Test Hailo with `hailortcli fw-control identify`
9. Print summary

### Verification
- Script runs without errors on Pi OS
- All checks report pass/warn/fail correctly

---

## Sub-Phase 9.2 — Requirements File

### Tasks

| ID | Task | Status |
|---|---|---|
| T026 | Create requirements.txt | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/requirements.txt` | Python dependencies |

### Verification
- `pip install -r requirements.txt` succeeds in clean venv

---

## Exit Criteria
- [ ] setup.sh installs all dependencies
- [ ] requirements.txt installs all Python packages
- [ ] Summary output clearly shows what passed/failed

## Risks

| Risk | Mitigation |
|---|---|
| Package names differ across distros | Target Raspberry Pi OS Bookworm specifically |
| rtl-biast not in default repos | May need to build from source |
