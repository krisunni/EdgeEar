# Phase 2 — Input Source Abstraction

## Objective
Implement the dual-mode input pipeline: SDR via rtl_fm, web stream via ffmpeg, unified behind the InputSource abstraction.

## Scope
- SDR auto-detection (`detect_sdr()`)
- `Tuner` class (rtl_fm process manager)
- `StreamSource` class (ffmpeg web stream ingest)
- `InputSource` abstraction (unified PCM queue)
- Updated preset schema with `stream_url`

---

## Sub-Phase 2.1 — InputSource & Auto-Detection

### Tasks

| ID | Task | Status |
|---|---|---|
| T004 | Implement `detect_sdr()` auto-detection | planned |
| T005 | Implement `InputSource` abstraction class | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/ravensdr/input_source.py` | InputSource class + detect_sdr() |

### Verification
- `detect_sdr()` returns False on laptop, True with SDR connected
- `InputSource("WEBSTREAM")` creates StreamSource
- `InputSource("SDR")` creates Tuner

---

## Sub-Phase 2.2 — Tuner (SDR Mode)

### Tasks

| ID | Task | Status |
|---|---|---|
| T006 | Implement Tuner class (rtl_fm manager) | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/ravensdr/tuner.py` | RTL-FM subprocess manager |

### Verification
- rtl_fm starts with correct flags
- PCM chunks appear in both queues
- `stop()` kills subprocess cleanly
- Frequency switch drains queues before restart

---

## Sub-Phase 2.3 — StreamSource (Web Stream Mode)

### Tasks

| ID | Task | Status |
|---|---|---|
| T007 | Implement StreamSource class (ffmpeg ingest) | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/ravensdr/stream_source.py` | ffmpeg web stream ingest |

### Verification
- ffmpeg connects to NOAA Monterey stream
- PCM chunks appear in queue
- Reconnect works after stream drop
- Stream switching kills and restarts subprocess

---

## Exit Criteria
- [ ] SDR auto-detection works
- [ ] Tuner produces PCM from rtl_fm
- [ ] StreamSource produces PCM from ffmpeg
- [ ] InputSource wraps both transparently
- [ ] Downstream code never knows which source is active

## Risks

| Risk | Mitigation |
|---|---|
| Web stream URLs go offline | Use confirmed NOAA Monterey as primary dev target |
| rtl_fm not installed on dev machine | Auto-detect and fall back to web stream |
| Queue overflow on slow consumers | maxsize=200 with blocking put |
