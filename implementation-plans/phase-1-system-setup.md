# Phase 1 — System Dependencies & Environment Setup

## Objective
Install all system packages, configure kernel modules, set up Python virtual environment, and verify hardware.

## Scope
- System packages (rtl-sdr, ffmpeg, sox, alsa-utils)
- ALSA loopback kernel module
- Python venv with pip packages
- Hailo SDK installation
- RTL-SDR driver configuration (DVB blacklist)

---

## Sub-Phase 1.1 — System Packages

### Tasks

| ID | Task | Status |
|---|---|---|
| T001 | Create `setup.sh` with apt install commands | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/setup.sh` | One-shot system dependency installer |

### Verification
- `rtl_test -t` shows "Found Rafael Micro R828D tuner"
- `ffmpeg -version` returns successfully
- `lsmod | grep snd_aloop` shows module loaded

---

## Sub-Phase 1.2 — Python Environment

### Tasks

| ID | Task | Status |
|---|---|---|
| T026 | Create `requirements.txt` | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/requirements.txt` | Python dependencies |

### Verification
- `pip install -r requirements.txt` completes without errors
- `python -c "import flask; import numpy"` succeeds

---

## Sub-Phase 1.3 — Hailo SDK

### Tasks

| ID | Task | Status |
|---|---|---|
| T002 | Install and verify Hailo SDK | planned |

### Verification
- `hailortcli fw-control identify` returns device info
- Whisper .hef model file present

---

## Sub-Phase 1.4 — RTL-SDR Driver

### Tasks

| ID | Task | Status |
|---|---|---|
| T003 | Blacklist DVB kernel module and verify RTL-SDR | planned |

### Verification
- DVB module blacklisted in `/etc/modprobe.d/rtlsdr.conf`
- `rtl_test -t` exit code 0

---

## Exit Criteria
- [ ] All system packages installed
- [ ] snd-aloop kernel module loaded and persisted
- [ ] Python venv created with all dependencies
- [ ] RTL-SDR detected (or gracefully absent for laptop dev)
- [ ] Hailo SDK verified (or noted as CPU-fallback mode)

## Risks

| Risk | Mitigation |
|---|---|
| Hailo SDK version mismatch | Follow official Pi 5 guide exactly |
| RTL-SDR not detected | Check USB, verify DVB blacklist |
| snd-aloop not available | May need kernel headers for module |
